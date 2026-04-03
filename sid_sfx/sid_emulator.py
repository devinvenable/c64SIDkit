"""Minimal SID voice emulator for WAV preview generation.

Emulates one SID voice: waveform generator + ADSR envelope.
Not cycle-accurate — designed for authoring preview, not chip-perfect playback.
Targets 8580 behavior as the preview baseline per project constraints.
"""

from __future__ import annotations

import numpy as np

from sid_sfx.schema import Waveform, ATTACK_MS, DECAY_RELEASE_MS


class SidVoiceEmulator:
    """Emulate a single SID voice for preview rendering."""

    def __init__(self, sample_rate: int = 44100, clock: float = 985248.0):
        self.sample_rate = sample_rate
        self.clock = clock  # PAL default

    def render(
        self,
        waveform: Waveform,
        frequency: int,
        attack: int,
        decay: int,
        sustain: int,
        release: int,
        pw_hi: int = 0x08,
        duration_ms: float = 500.0,
        gate_off_ms: float | None = None,
        sweep_target: int = 0,
        sweep_type: str = "exponential",
        vibrato_rate: float = 0.0,
        vibrato_depth: int = 0,
        filter_mode: str = "off",
        filter_cutoff: int = 0x90,
        filter_resonance: int = 0xF,
        filter_cutoff_sweep: int = 0,
    ) -> np.ndarray:
        """Render a gated SID voice to float32 samples [-1, 1].

        Args:
            waveform: Waveform type.
            frequency: 16-bit SID frequency register value.
            attack/decay/sustain/release: Nibble values 0-15.
            pw_hi: Pulse width high byte (0-255). Duty = pw_hi/256.
            duration_ms: Total render duration.
            gate_off_ms: When to release gate. If None, uses attack+decay time.
            sweep_target: End frequency (16-bit SID register). 0 = no sweep.
            sweep_type: "linear" or "exponential".
        """
        sr = self.sample_rate
        n_samples = int(sr * duration_ms / 1000.0)

        # Frequency in Hz
        freq_hz = frequency * self.clock / (1 << 24)
        if freq_hz < 1.0:
            freq_hz = 1.0

        has_vibrato = vibrato_rate > 0 and vibrato_depth > 0

        if sweep_target > 0 or has_vibrato:
            end_hz = freq_hz
            if sweep_target > 0:
                end_hz = sweep_target * self.clock / (1 << 24)
                if end_hz < 1.0:
                    end_hz = 1.0
            wave = self._generate_modulated_waveform(
                waveform, freq_hz, end_hz, n_samples, pw_hi,
                sweep_type if sweep_target > 0 else "linear",
                has_sweep=sweep_target > 0,
                vibrato_rate=vibrato_rate if has_vibrato else 0.0,
                vibrato_depth_hz=vibrato_depth * self.clock / (1 << 24) if has_vibrato else 0.0,
            )
        else:
            # Generate waveform
            wave = self._generate_waveform(waveform, freq_hz, n_samples, pw_hi)

        # Generate envelope
        envelope = self._generate_envelope(
            attack, decay, sustain, release,
            n_samples, gate_off_ms, duration_ms,
        )

        # Apply filter if enabled
        if filter_mode != "off":
            wave = self._apply_filter(
                wave, filter_mode, filter_cutoff, filter_resonance,
                filter_cutoff_sweep, n_samples,
            )

        return (wave * envelope).astype(np.float32)

    def _generate_modulated_waveform(
        self,
        waveform: Waveform,
        start_hz: float,
        end_hz: float,
        n_samples: int,
        pw_hi: int,
        sweep_type: str,
        has_sweep: bool = True,
        vibrato_rate: float = 0.0,
        vibrato_depth_hz: float = 0.0,
    ) -> np.ndarray:
        """Generate waveform with frequency sweep and/or vibrato using a phase accumulator."""
        t = np.arange(n_samples, dtype=np.float64) / self.sample_rate
        frac = t * self.sample_rate / max(1, n_samples)  # 0→1 over duration

        if has_sweep:
            if sweep_type == "exponential" and start_hz > 0 and end_hz > 0:
                freq_curve = start_hz * np.power(end_hz / start_hz, frac)
            else:
                freq_curve = start_hz + (end_hz - start_hz) * frac
        else:
            freq_curve = np.full(n_samples, start_hz, dtype=np.float64)

        # Apply vibrato: periodic frequency modulation
        if vibrato_rate > 0 and vibrato_depth_hz > 0:
            vibrato_mod = vibrato_depth_hz * np.sin(2.0 * np.pi * vibrato_rate * t)
            freq_curve = np.maximum(1.0, freq_curve + vibrato_mod)

        # Phase accumulator: integrate instantaneous frequency
        phase_increment = freq_curve / self.sample_rate
        phase = np.cumsum(phase_increment) % 1.0

        return self._waveform_from_phase(waveform, phase, pw_hi)

    def _waveform_from_phase(
        self, waveform: Waveform, phase: np.ndarray, pw_hi: int
    ) -> np.ndarray:
        """Convert a phase array [0,1) to waveform samples."""
        if waveform == Waveform.TRIANGLE:
            return 2.0 * np.abs(2.0 * phase - 1.0) - 1.0
        elif waveform == Waveform.SAWTOOTH:
            return 2.0 * phase - 1.0
        elif waveform == Waveform.PULSE:
            duty = pw_hi / 256.0
            if duty < 0.001:
                duty = 0.5
            return np.where(phase < duty, 1.0, -1.0).astype(np.float64)
        elif waveform == Waveform.NOISE:
            # For swept noise, use sample-and-hold with average freq
            avg_freq = np.mean(phase)  # rough approximation
            n_samples = len(phase)
            samples_per_cycle = max(1, int(1.0 / max(0.001, np.mean(np.diff(phase[phase < 0.99])))))
            noise_len = (n_samples // samples_per_cycle) + 2
            rng = np.random.default_rng(42)
            noise_values = rng.uniform(-1.0, 1.0, noise_len)
            indices = np.arange(n_samples) // samples_per_cycle
            indices = np.clip(indices, 0, noise_len - 1)
            return noise_values[indices]
        else:
            raise ValueError(f"Unknown waveform: {waveform}")

    def _apply_filter(
        self,
        samples: np.ndarray,
        mode: str,
        cutoff: int,
        resonance: int,
        cutoff_sweep: int,
        n_samples: int,
    ) -> np.ndarray:
        """Apply a state-variable filter approximating the SID filter.

        Uses a simple SVF: low-pass, band-pass, or high-pass with resonance.
        Cutoff is mapped from SID SIDFCHI byte (0-255) to frequency.
        """
        # Map SID cutoff byte to frequency (~30Hz to ~12kHz, roughly logarithmic)
        def cutoff_to_freq(c):
            return 30.0 * (2.0 ** (c / 255.0 * 8.5))

        start_freq = cutoff_to_freq(cutoff)
        if cutoff_sweep > 0:
            end_freq = cutoff_to_freq(cutoff_sweep)
        else:
            end_freq = start_freq

        # Resonance: SID nibble 0-15 maps to Q ~0.5 to ~15
        q = 0.5 + (resonance / 15.0) * 14.5

        # State-variable filter
        out = np.zeros(n_samples, dtype=np.float64)
        lp = 0.0  # low-pass state
        bp = 0.0  # band-pass state

        for i in range(n_samples):
            # Interpolate cutoff frequency
            frac = i / max(1, n_samples - 1)
            if cutoff_sweep > 0:
                fc = start_freq * ((end_freq / start_freq) ** frac)
            else:
                fc = start_freq

            # SVF coefficient
            f = 2.0 * np.sin(np.pi * min(fc / self.sample_rate, 0.49))
            q_inv = 1.0 / q

            # SVF update
            hp = samples[i] - lp - q_inv * bp
            bp += f * hp
            lp += f * bp

            if mode == "lowpass":
                out[i] = lp
            elif mode == "bandpass":
                out[i] = bp
            elif mode == "highpass":
                out[i] = hp
            else:
                out[i] = samples[i]

        return out

    def _generate_waveform(
        self, waveform: Waveform, freq_hz: float, n_samples: int, pw_hi: int
    ) -> np.ndarray:
        t = np.arange(n_samples, dtype=np.float64) / self.sample_rate
        phase = (t * freq_hz) % 1.0

        if waveform == Waveform.TRIANGLE:
            return (2.0 * np.abs(2.0 * phase - 1.0) - 1.0)
        elif waveform == Waveform.SAWTOOTH:
            return 2.0 * phase - 1.0
        elif waveform == Waveform.PULSE:
            duty = pw_hi / 256.0
            if duty < 0.001:
                duty = 0.5  # Default to 50% if unset
            return np.where(phase < duty, 1.0, -1.0).astype(np.float64)
        elif waveform == Waveform.NOISE:
            # SID noise is LFSR-based; approximate with sample-and-hold noise
            # at the SID oscillator rate
            samples_per_cycle = max(1, int(self.sample_rate / freq_hz))
            noise_len = (n_samples // samples_per_cycle) + 2
            rng = np.random.default_rng(42)
            noise_values = rng.uniform(-1.0, 1.0, noise_len)
            indices = np.arange(n_samples) // samples_per_cycle
            indices = np.clip(indices, 0, noise_len - 1)
            return noise_values[indices]
        else:
            raise ValueError(f"Unknown waveform: {waveform}")

    def _generate_envelope(
        self,
        attack: int,
        decay: int,
        sustain: int,
        release: int,
        n_samples: int,
        gate_off_ms: float | None,
        duration_ms: float,
    ) -> np.ndarray:
        """Generate ADSR envelope matching SID timing tables."""
        sr = self.sample_rate

        attack_ms = ATTACK_MS[attack]
        decay_ms = DECAY_RELEASE_MS[decay]
        release_ms = DECAY_RELEASE_MS[release]
        sustain_level = sustain / 15.0

        if gate_off_ms is None:
            gate_off_ms = attack_ms + decay_ms + 50.0  # Small sustain hold

        attack_samples = int(sr * attack_ms / 1000.0)
        decay_samples = int(sr * decay_ms / 1000.0)
        release_samples = int(sr * release_ms / 1000.0)
        gate_off_sample = int(sr * gate_off_ms / 1000.0)

        envelope = np.zeros(n_samples, dtype=np.float64)
        level = 0.0

        # State machine: attack -> decay -> sustain -> release
        for i in range(n_samples):
            if i < gate_off_sample:
                # Gate ON phase
                if i < attack_samples:
                    # Attack: ramp to 1.0
                    level = i / max(1, attack_samples)
                elif i < attack_samples + decay_samples:
                    # Decay: fall from 1.0 to sustain_level
                    decay_pos = (i - attack_samples) / max(1, decay_samples)
                    level = 1.0 - (1.0 - sustain_level) * decay_pos
                else:
                    # Sustain
                    level = sustain_level
            else:
                # Release phase
                release_pos = i - gate_off_sample
                if release_samples > 0 and release_pos < release_samples:
                    level = sustain_level * (1.0 - release_pos / release_samples)
                else:
                    level = 0.0
            envelope[i] = max(0.0, level)

        return envelope
