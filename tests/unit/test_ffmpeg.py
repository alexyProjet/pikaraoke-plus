"""Unit tests for ffmpeg module."""

from unittest.mock import MagicMock, patch

import pytest

from pikaraoke.lib.ffmpeg import (
    build_ffmpeg_cmd,
    get_ffmpeg_version,
    get_media_duration,
    is_ffmpeg_installed,
    is_transpose_enabled,
    supports_hardware_h264_encoding,
)


def make_file_resolver(extension: str = ".mp4") -> MagicMock:
    """Create a mock FileResolver for build_ffmpeg_cmd tests."""
    fr = MagicMock()
    fr.file_path = f"/songs/test{extension}"
    fr.file_extension = extension
    fr.cdg_file_path = None
    fr.output_file = "/tmp/out.m3u8"
    fr.init_filename = "init.mp4"
    fr.segment_pattern = "/tmp/seg_%03d.m4s"
    return fr


def _mock_probe_with_audio(codec_name):
    """Build an ffmpeg.probe result with a single audio stream."""
    return {"streams": [{"codec_type": "audio", "codec_name": codec_name}]}


class TestBuildFfmpegCmdHlsAudio:
    """Tests for audio codec selection in the HLS output branch."""

    def test_clean_aac_source_copies_audio(self):
        """Test that an untouched AAC source copies the audio stream."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.return_value = _mock_probe_with_audio("aac")
            cmd = build_ffmpeg_cmd(make_file_resolver(), semitones=0, normalize_audio=False)
        args = cmd.get_args()
        assert args[args.index("-acodec") + 1] == "copy"

    def test_non_aac_source_reencodes_audio(self):
        """Test that mp4 containers with non-AAC audio (AC-3, MP3) re-encode."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.return_value = _mock_probe_with_audio("ac3")
            cmd = build_ffmpeg_cmd(make_file_resolver(), semitones=0, normalize_audio=False)
        args = cmd.get_args()
        assert args[args.index("-acodec") + 1] == "aac"

    def test_unprobeable_source_reencodes_audio(self):
        """Test that a failed probe falls back to safe re-encoding."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.side_effect = OSError("probe failed")
            cmd = build_ffmpeg_cmd(make_file_resolver(), semitones=0, normalize_audio=False)
        args = cmd.get_args()
        assert args[args.index("-acodec") + 1] == "aac"

    def test_transposed_source_reencodes_audio(self):
        """Test that pitch shifting forces AAC re-encoding."""
        cmd = build_ffmpeg_cmd(make_file_resolver(), semitones=2, normalize_audio=False)
        args = cmd.get_args()
        assert args[args.index("-acodec") + 1] == "aac"

    def test_normalized_source_reencodes_audio(self):
        """Test that loudness normalization forces AAC re-encoding."""
        cmd = build_ffmpeg_cmd(make_file_resolver(), semitones=0, normalize_audio=True)
        args = cmd.get_args()
        assert args[args.index("-acodec") + 1] == "aac"


class TestGetFfmpegVersion:
    """Tests for the get_ffmpeg_version function."""

    def test_version_parsed_correctly(self):
        """Test parsing FFmpeg version from output."""
        mock_result = MagicMock()
        mock_result.stdout = "ffmpeg version 5.1.2 Copyright (c) 2000-2022"

        with patch("subprocess.run", return_value=mock_result):
            result = get_ffmpeg_version()
            assert result == "5.1.2"

    def test_ffmpeg_not_installed(self):
        """Test handling when FFmpeg is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = get_ffmpeg_version()
            assert result == "FFmpeg is not installed"

    def test_unable_to_parse_version(self):
        """Test handling when version can't be parsed."""
        mock_result = MagicMock()
        mock_result.stdout = "unexpected format"

        with patch("subprocess.run", return_value=mock_result):
            result = get_ffmpeg_version()
            assert result == "Unable to parse FFmpeg version"


class TestIsTransposeEnabled:
    """Tests for the is_transpose_enabled function."""

    def test_rubberband_available(self):
        """Test when rubberband filter is available."""
        mock_result = MagicMock()
        mock_result.stdout = b"... rubberband ... other filters"

        with patch("subprocess.run", return_value=mock_result):
            assert is_transpose_enabled() is True

    def test_rubberband_not_available(self):
        """Test when rubberband filter is not available."""
        mock_result = MagicMock()
        mock_result.stdout = b"aecho, aresample, volume"

        with patch("subprocess.run", return_value=mock_result):
            assert is_transpose_enabled() is False

    def test_ffmpeg_not_installed(self):
        """Test when FFmpeg is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_transpose_enabled() is False


class TestSupportsHardwareH264Encoding:
    """Tests for the supports_hardware_h264_encoding function."""

    def test_x86_returns_false(self):
        """Test that x86 architecture returns False."""
        with patch("platform.machine", return_value="x86_64"):
            assert supports_hardware_h264_encoding() is False

    def test_intel_returns_false(self):
        """Test that Intel architecture returns False."""
        with patch("platform.machine", return_value="i686"):
            assert supports_hardware_h264_encoding() is False

    def test_arm_with_encoder(self):
        """Test ARM with h264_v4l2m2m available."""
        mock_result = MagicMock()
        mock_result.stdout = b"h264_v4l2m2m encoder available"

        with patch("platform.machine", return_value="aarch64"):
            with patch("subprocess.run", return_value=mock_result):
                assert supports_hardware_h264_encoding() is True

    def test_arm_without_encoder(self):
        """Test ARM without h264_v4l2m2m available."""
        mock_result = MagicMock()
        mock_result.stdout = b"libx264 encoder only"

        with patch("platform.machine", return_value="armv7l"):
            with patch("subprocess.run", return_value=mock_result):
                assert supports_hardware_h264_encoding() is False

    def test_arm_ffmpeg_not_found(self):
        """Test ARM when FFmpeg is not installed."""
        with patch("platform.machine", return_value="aarch64"):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                assert supports_hardware_h264_encoding() is False

    def test_pi_5_returns_false_despite_codec_listed(self):
        """Test that a Pi 5 uses software encoding even when ffmpeg lists h264_v4l2m2m."""
        mock_result = MagicMock()
        mock_result.stdout = b"h264_v4l2m2m encoder available"

        with patch("platform.machine", return_value="aarch64"):
            with patch("pikaraoke.lib.ffmpeg.get_raspberry_pi_model", return_value=5):
                with patch("subprocess.run", return_value=mock_result):
                    assert supports_hardware_h264_encoding() is False

    def test_pi_4_uses_hardware_encoder(self):
        """Test that a Pi 4 still uses the hardware encoder."""
        mock_result = MagicMock()
        mock_result.stdout = b"h264_v4l2m2m encoder available"

        with patch("platform.machine", return_value="aarch64"):
            with patch("pikaraoke.lib.ffmpeg.get_raspberry_pi_model", return_value=4):
                with patch("subprocess.run", return_value=mock_result):
                    assert supports_hardware_h264_encoding() is True


class TestIsFfmpegInstalled:
    """Tests for the is_ffmpeg_installed function."""

    def test_ffmpeg_installed(self):
        """Test when FFmpeg is installed."""
        with patch("subprocess.run", return_value=MagicMock()):
            assert is_ffmpeg_installed() is True

    def test_ffmpeg_not_installed(self):
        """Test when FFmpeg is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert is_ffmpeg_installed() is False


class TestGetMediaDuration:
    """Tests for the get_media_duration function."""

    def test_returns_duration_rounded(self):
        """Test that duration is returned as rounded integer."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.return_value = {"format": {"duration": "183.456"}}
            result = get_media_duration("/path/to/video.mp4")
            assert result == 183

    def test_returns_none_on_probe_error(self):
        """Test that None is returned when probe fails."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.side_effect = Exception("Probe failed")
            result = get_media_duration("/path/to/invalid.mp4")
            assert result is None

    def test_returns_none_on_missing_duration(self):
        """Test that None is returned when duration key is missing."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.return_value = {"format": {}}
            result = get_media_duration("/path/to/video.mp4")
            assert result is None

    def test_handles_integer_duration(self):
        """Test handling of integer duration value."""
        with patch("pikaraoke.lib.ffmpeg.ffmpeg.probe") as mock_probe:
            mock_probe.return_value = {"format": {"duration": "120"}}
            result = get_media_duration("/path/to/video.mp4")
            assert result == 120


class TestIsTransposeEnabledIndexError:
    """Additional tests for is_transpose_enabled IndexError handling."""

    def test_index_error_returns_false(self):
        """Test that IndexError returns False."""
        with patch("subprocess.run", side_effect=IndexError):
            assert is_transpose_enabled() is False


class TestSupportsHardwareH264EncodingIndexError:
    """Additional tests for supports_hardware_h264_encoding IndexError handling."""

    def test_index_error_returns_false(self):
        """Test that IndexError on ARM returns False."""
        with patch("platform.machine", return_value="aarch64"):
            with patch("subprocess.run", side_effect=IndexError):
                assert supports_hardware_h264_encoding() is False
