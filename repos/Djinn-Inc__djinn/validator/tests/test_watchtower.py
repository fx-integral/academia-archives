"""Tests for the watchtower auto-update module."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from djinn_validator.utils import watchtower
from djinn_validator.utils.watchtower import (
    _ensure_remote,
    _find_repo_root,
    _install_deps,
    _local_sha,
    _pull,
    _remote_sha,
    _verify_commit_signature,
    watch_loop,
)


class TestMultiRemote:
    def test_remote_sha_falls_through_to_second(self, tmp_path: Path) -> None:
        """First remote returns nothing, second returns a sha — should
        report the second remote as the source."""
        call_log = []

        def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            call_log.append(cmd)
            if "ls-remote" in cmd:
                remote = cmd[cmd.index("ls-remote") + 1]
                if remote == "origin":
                    return MagicMock(returncode=1, stdout="", stderr="connection refused")
                if remote == "codeberg":
                    return MagicMock(returncode=0, stdout="abc123\trefs/heads/main\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(watchtower, "_REMOTES", ["origin", "codeberg"]),
            patch.object(watchtower, "_run", side_effect=fake_run),
        ):
            sha, name = _remote_sha(tmp_path, "main")
            assert sha == "abc123"
            assert name == "codeberg"

    def test_pull_falls_through_to_second_remote(self, tmp_path: Path) -> None:
        """First pull fails, second succeeds — overall pull returns True."""
        outcomes = {"origin": False, "codeberg": True}

        def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            if "pull" in cmd:
                remote = cmd[cmd.index("pull") + 2]
                if outcomes.get(remote, False):
                    return MagicMock(returncode=0, stdout="ok", stderr="")
                return MagicMock(returncode=1, stdout="", stderr="conn refused")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(watchtower, "_REMOTES", ["origin", "codeberg"]),
            patch.object(watchtower, "_run", side_effect=fake_run),
        ):
            assert _pull(tmp_path, "main") is True

    def test_pull_returns_false_when_all_remotes_fail(self, tmp_path: Path) -> None:
        def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            if "pull" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="conn refused")
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(watchtower, "_REMOTES", ["origin", "codeberg"]),
            patch.object(watchtower, "_run", side_effect=fake_run),
        ):
            assert _pull(tmp_path, "main") is False

    def test_ensure_remote_creates_when_missing(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if "get-url" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="No such remote")
            if "add" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(watchtower, "_run", side_effect=fake_run):
            assert _ensure_remote(tmp_path, "codeberg", "https://example.com/x.git") is True
        assert any("add" in c for c in calls)

    def test_ensure_remote_updates_when_url_differs(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if "get-url" in cmd:
                return MagicMock(returncode=0, stdout="https://old.example.com/x.git", stderr="")
            if "set-url" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(watchtower, "_run", side_effect=fake_run):
            assert _ensure_remote(tmp_path, "codeberg", "https://new.example.com/x.git") is True
        assert any("set-url" in c for c in calls)

    def test_ensure_remote_noop_when_url_matches(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if "get-url" in cmd:
                return MagicMock(returncode=0, stdout="https://same.example.com/x.git", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(watchtower, "_run", side_effect=fake_run):
            assert _ensure_remote(tmp_path, "codeberg", "https://same.example.com/x.git") is True
        # Only the get-url call, no add or set-url
        assert all("add" not in c and "set-url" not in c for c in calls)


class TestConfig:
    def test_disabled_by_default(self) -> None:
        assert not watchtower._ENABLED

    def test_default_branch(self) -> None:
        assert watchtower._BRANCH == "main"

    def test_default_interval(self) -> None:
        assert watchtower._INTERVAL == 900


class TestFindRepoRoot:
    def test_returns_path_when_git_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch.dict("os.environ", {"AUTO_UPDATE_REPO_ROOT": str(tmp_path)}):
            result = _find_repo_root()
        assert result == tmp_path

    def test_returns_none_when_no_git_dir(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"AUTO_UPDATE_REPO_ROOT": str(tmp_path)}):
            result = _find_repo_root()
        assert result is None

    def test_empty_override_falls_back_to_walk(self) -> None:
        with patch.dict("os.environ", {"AUTO_UPDATE_REPO_ROOT": ""}):
            root = _find_repo_root()
            # Module lives inside the djinn repo, should find it
            assert root is not None


class TestLocalSha:
    def test_returns_sha(self, tmp_path: Path) -> None:
        with patch("djinn_validator.utils.watchtower._run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")
            assert _local_sha(tmp_path) == "abc123"

    def test_returns_none_on_failure(self, tmp_path: Path) -> None:
        with patch("djinn_validator.utils.watchtower._run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert _local_sha(tmp_path) is None


class TestRemoteSha:
    def test_returns_sha(self, tmp_path: Path) -> None:
        with patch("djinn_validator.utils.watchtower._run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="def456\trefs/heads/main\n")
            sha, name = _remote_sha(tmp_path, "main")
            assert sha == "def456"
            assert name == "origin"

    def test_returns_none_on_failure(self, tmp_path: Path) -> None:
        with patch("djinn_validator.utils.watchtower._run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            sha, name = _remote_sha(tmp_path, "main")
            assert sha is None
            assert name is None


class TestPull:
    @patch("djinn_validator.utils.watchtower._run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Already up to date.",
        )
        assert _pull(Path("/fake"), "main") is True

    @patch("djinn_validator.utils.watchtower._run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="merge conflict",
        )
        assert _pull(Path("/fake"), "main") is False


class TestInstallDeps:
    @patch("djinn_validator.utils.watchtower._run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
        )
        assert _install_deps(Path("/fake")) is True

    @patch("djinn_validator.utils.watchtower._run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="error",
        )
        assert _install_deps(Path("/fake")) is False

    @patch("djinn_validator.utils.watchtower._run")
    def test_uv_not_found_falls_back_to_pip(self, mock_run: MagicMock) -> None:
        # shield_dir doesn't exist for /fake, so no shield call.
        # First call (uv sync) raises FileNotFoundError,
        # second call (pip install fallback) succeeds.
        mock_run.side_effect = [
            FileNotFoundError("uv not found"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout=""),
        ]
        assert _install_deps(Path("/fake")) is True

    @patch("djinn_validator.utils.watchtower._run")
    def test_uv_not_found_pip_fails_returns_false(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            FileNotFoundError("uv not found"),
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="pip failed"),
        ]
        assert _install_deps(Path("/fake")) is False


class TestVerifyCommitSignature:
    @patch("djinn_validator.utils.watchtower._run")
    def test_good_signature_logs_info(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="G|abc123def456|Alice\n",
        )
        # Should not raise; just logs info
        _verify_commit_signature(Path("/fake"))
        mock_run.assert_called_once()

    @patch("djinn_validator.utils.watchtower._run")
    def test_untrusted_signature_logs_info(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="U|abc123def456|Bob\n",
        )
        _verify_commit_signature(Path("/fake"))
        mock_run.assert_called_once()

    @patch("djinn_validator.utils.watchtower._run")
    def test_unsigned_commit_logs_warning(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="N|abc123def456|Charlie\n",
        )
        _verify_commit_signature(Path("/fake"))
        mock_run.assert_called_once()

    @patch("djinn_validator.utils.watchtower._run")
    def test_bad_signature_logs_warning(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="B|abc123def456|Eve\n",
        )
        _verify_commit_signature(Path("/fake"))
        mock_run.assert_called_once()

    @patch("djinn_validator.utils.watchtower._run")
    def test_git_failure_logs_warning(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="fatal: not a repo",
        )
        _verify_commit_signature(Path("/fake"))

    @patch("djinn_validator.utils.watchtower._run")
    def test_parse_error_logs_warning(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="garbage\n",
        )
        _verify_commit_signature(Path("/fake"))

    @patch("djinn_validator.utils.watchtower._run", side_effect=Exception("boom"))
    def test_exception_logs_warning(self, mock_run: MagicMock) -> None:
        _verify_commit_signature(Path("/fake"))


class TestWatchLoop:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self) -> None:
        """watch_loop returns immediately when AUTO_UPDATE is not set."""
        with patch.object(watchtower, "_ENABLED", False):
            await asyncio.wait_for(watch_loop(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_no_repo_root_exits(self) -> None:
        with patch.object(watchtower, "_ENABLED", True), patch.object(watchtower, "_find_repo_root", return_value=None):
            await asyncio.wait_for(watch_loop(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_detects_update_and_restarts(self) -> None:
        with (
            patch.object(watchtower, "_ENABLED", True),
            patch.object(watchtower, "_INTERVAL", 0),
            patch.object(watchtower, "_find_repo_root", return_value=Path("/fake")),
            patch.object(watchtower, "_local_sha", return_value="aaa"),
            patch.object(watchtower, "_remote_sha", return_value=("bbb", "origin")),
            patch.object(watchtower, "_pull", return_value=True) as mock_pull,
            patch.object(watchtower, "_verify_commit_signature"),
            patch.object(watchtower, "_install_deps", return_value=True) as mock_deps,
            patch.object(watchtower, "_ensure_configured_remotes"),
            patch.object(watchtower, "_restart") as mock_restart,
        ):
            mock_restart.side_effect = SystemExit(0)
            with pytest.raises(SystemExit):
                await watch_loop(package_dir=Path("/fake"))
            mock_pull.assert_called_once_with(Path("/fake"), "main", preferred_remote="origin")
            mock_deps.assert_called_once_with(Path("/fake"))
            mock_restart.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_up_to_date(self) -> None:
        call_count = 0

        original_sleep = asyncio.sleep

        async def _counting_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with (
            patch.object(watchtower, "_ENABLED", True),
            patch.object(watchtower, "_INTERVAL", 0),
            patch.object(watchtower, "_find_repo_root", return_value=Path("/fake")),
            patch.object(watchtower, "_local_sha", return_value="same"),
            patch.object(watchtower, "_remote_sha", return_value=("same", "origin")),
            patch.object(watchtower, "_pull") as mock_pull,
            patch.object(watchtower, "_ensure_configured_remotes"),
            patch.object(watchtower, "_restart") as mock_restart,
            patch("asyncio.sleep", side_effect=_counting_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watch_loop(package_dir=Path("/fake"))
            mock_pull.assert_not_called()
            mock_restart.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_pull_failure(self) -> None:
        call_count = 0

        async def _counting_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError

        with (
            patch.object(watchtower, "_ENABLED", True),
            patch.object(watchtower, "_INTERVAL", 0),
            patch.object(watchtower, "_find_repo_root", return_value=Path("/fake")),
            patch.object(watchtower, "_local_sha", return_value="aaa"),
            patch.object(watchtower, "_remote_sha", return_value=("bbb", "origin")),
            patch.object(watchtower, "_pull", return_value=False),
            patch.object(watchtower, "_ensure_configured_remotes"),
            patch.object(watchtower, "_restart") as mock_restart,
            patch("asyncio.sleep", side_effect=_counting_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watch_loop(package_dir=Path("/fake"))
            mock_restart.assert_not_called()
