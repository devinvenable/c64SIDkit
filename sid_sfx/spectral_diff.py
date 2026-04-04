"""Spectral comparison utilities for SID backend render outputs."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import stft

from sid_sfx.schema import SfxPatch
from sid_sfx.wav_export import render_patch_to_wav


def _load_wav_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """Load a mono WAV and return float32 samples in [-1, 1] plus sample rate."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sample_width == 1:
        data = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    return data.astype(np.float32, copy=False), sample_rate


def _coerce_audio(
    value: str | Path | np.ndarray | tuple[np.ndarray, int],
    default_sample_rate: int = 44100,
) -> tuple[np.ndarray, int]:
    if isinstance(value, (str, Path)):
        return _load_wav_mono(value)
    if isinstance(value, tuple) and len(value) == 2:
        samples, sample_rate = value
        return np.asarray(samples, dtype=np.float32), int(sample_rate)
    return np.asarray(value, dtype=np.float32), default_sample_rate


def _pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    x = x.astype(np.float64, copy=False).ravel()
    y = y.astype(np.float64, copy=False).ravel()
    x -= x.mean()
    y -= y.mean()
    denom = np.linalg.norm(x) * np.linalg.norm(y)
    if denom <= 0:
        return 0.0
    return float(np.dot(x, y) / denom)


def _frame_rms(samples: np.ndarray, frame_size: int, hop: int) -> np.ndarray:
    if samples.size < frame_size:
        samples = np.pad(samples, (0, frame_size - samples.size))
    frame_count = 1 + (samples.size - frame_size) // hop
    rms = np.empty(frame_count, dtype=np.float64)
    for i in range(frame_count):
        start = i * hop
        frame = samples[start : start + frame_size]
        rms[i] = np.sqrt(np.mean(np.square(frame, dtype=np.float64)))
    return rms


def spectral_similarity(
    wav_a: str | Path | np.ndarray | tuple[np.ndarray, int],
    wav_b: str | Path | np.ndarray | tuple[np.ndarray, int],
) -> dict[str, Any]:
    """Compare two renders and compute spectral similarity metrics."""
    audio_a, sample_rate_a = _coerce_audio(wav_a)
    audio_b, sample_rate_b = _coerce_audio(wav_b)
    if sample_rate_a != sample_rate_b:
        raise ValueError(f"Sample rates differ: {sample_rate_a} != {sample_rate_b}")

    sample_rate = sample_rate_a
    min_len = min(audio_a.size, audio_b.size)
    if min_len == 0:
        raise ValueError("Cannot compare empty audio")
    audio_a = audio_a[:min_len]
    audio_b = audio_b[:min_len]

    nperseg = 1024
    hop = nperseg // 2
    freqs, _, spec_a = stft(audio_a, fs=sample_rate, window="hann", nperseg=nperseg)
    _, _, spec_b = stft(audio_b, fs=sample_rate, window="hann", nperseg=nperseg)

    mag_a = np.abs(spec_a)
    mag_b = np.abs(spec_b)
    time_bins = min(mag_a.shape[1], mag_b.shape[1])
    mag_a = mag_a[:, :time_bins]
    mag_b = mag_b[:, :time_bins]

    spectral_corr = _pearson_corr(mag_a, mag_b)

    rms_a = _frame_rms(audio_a, frame_size=nperseg, hop=hop)
    rms_b = _frame_rms(audio_b, frame_size=nperseg, hop=hop)
    env_bins = min(rms_a.size, rms_b.size)
    rms_a_db = 20.0 * np.log10(np.maximum(rms_a[:env_bins], 1e-12))
    rms_b_db = 20.0 * np.log10(np.maximum(rms_b[:env_bins], 1e-12))
    rms_env_diff_db = float(np.mean(np.abs(rms_a_db - rms_b_db)))

    peak_idx_a = np.argmax(mag_a, axis=0)
    peak_idx_b = np.argmax(mag_b, axis=0)
    peak_freq_a = freqs[peak_idx_a]
    peak_freq_b = freqs[peak_idx_b]
    peak_freq_diff_hz = np.abs(peak_freq_a - peak_freq_b)
    peak_alignment_pct = float(np.mean(peak_freq_diff_hz <= 50.0) * 100.0)

    corr_score = ((spectral_corr + 1.0) / 2.0) * 100.0
    rms_score = max(0.0, 100.0 - (rms_env_diff_db * 8.0))
    overall_similarity = 0.5 * corr_score + 0.25 * rms_score + 0.25 * peak_alignment_pct

    return {
        "sample_rate": sample_rate,
        "duration_seconds": min_len / float(sample_rate),
        "stft_nperseg": nperseg,
        "spectral_correlation": float(np.clip(spectral_corr, -1.0, 1.0)),
        "rms_envelope_diff_db": rms_env_diff_db,
        "peak_freq_alignment_pct": peak_alignment_pct,
        "peak_freq_mean_diff_hz": float(np.mean(peak_freq_diff_hz)),
        "overall_similarity_pct": float(np.clip(overall_similarity, 0.0, 100.0)),
    }


def generate_diff_report(
    patch_path: str | Path,
    backend_a: str,
    backend_b: str,
    output_dir: str | Path | None = None,
    chip_model: str = "8580",
    sample_rate: int = 44100,
) -> str:
    """Render a patch with two backends and return a readable comparison report."""
    patch_file = Path(patch_path)
    patch = SfxPatch.load_json(patch_file)

    out_dir = Path(output_dir) if output_dir is not None else patch_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = patch_file.stem
    wav_a = out_dir / f"{base_name}_{backend_a}.wav"
    wav_b = out_dir / f"{base_name}_{backend_b}.wav"

    render_patch_to_wav(
        patch,
        wav_a,
        sample_rate=sample_rate,
        emulator=backend_a,
        chip_model=chip_model,
    )
    render_patch_to_wav(
        patch,
        wav_b,
        sample_rate=sample_rate,
        emulator=backend_b,
        chip_model=chip_model,
    )

    metrics = spectral_similarity(wav_a, wav_b)
    lines = [
        f"Comparing {patch.name}: {backend_a} vs {backend_b}",
        "----------------------------------",
        f"Spectral correlation:  {metrics['spectral_correlation']:.4f}",
        f"RMS envelope diff:     {metrics['rms_envelope_diff_db']:.2f} dB",
        f"Peak freq alignment:   {metrics['peak_freq_alignment_pct']:.1f}%",
        f"Overall similarity:    {metrics['overall_similarity_pct']:.1f}%",
        "",
        "WAVs saved:",
        f"  {wav_a}",
        f"  {wav_b}",
    ]
    return "\n".join(lines)
