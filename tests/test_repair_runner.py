#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
'''Tests for the repair runner's version handling.

The app version can carry a pre-release suffix ("5.5.0-beta0") and the
version.info file can carry a trailing '+' marking that repairs have already
run. Both must be ignored when comparing versions, otherwise the runner
crashes on startup or re-runs repairs that already completed.
'''

import importlib.util
from textwrap import dedent

import pytest

from context_chat_backend.repair import runner

# every release tag this repository has published
SHIPPED_VERSIONS = [
	'0.1.0', '1.0.0', '1.0.1', '1.1.0', '2.0.0', '2.0.1', '2.1.0', '2.2.0', '2.3.0',
	'2.4.0', '3.0.0', '3.1.0', '4.0.0-beta', '4.0.0-beta2', '4.0.0-beta3', '4.0.0-beta4',
	'4.0.0-beta5', '4.0.0', '4.0.1', '4.0.2', '4.0.3', '4.0.4', '4.0.5', '4.0.6',
	'4.0.7', '4.1.0', '4.1.1', '4.2.0', '4.3.0', '4.4.0', '4.4.1', '4.5.0',
	'4.5.0-beta.0', '4.5.0-beta.1', '4.5.0-beta.2', '4.5.0-beta.3', '4.6.0', '5.0.0',
	'5.0.1', '5.1.0', '5.2.0', '5.3.0', '5.4.0', '5.4.0-beta0', '5.4.1', '5.5.0-beta0',
]


class TestParseVersion:
	@pytest.mark.parametrize('version_string', SHIPPED_VERSIONS)
	def test_every_shipped_version_parses(self, version_string: str):
		'''No released tag may crash the parser, with or without the repairs-done marker.'''
		assert runner._parse_version(version_string) > 0
		assert runner._parse_version(version_string + '+') > 0

	@pytest.mark.parametrize('suffix', [
		'-beta0',      # 5.5.0-beta0, 5.4.0-beta0
		'-beta.3',     # 4.5.0-beta.3
		'-beta',       # 4.0.0-beta, no trailing number at all
		'-beta5',
		'-alpha1',
		'-alpha',
		'-rc1',
		'-rc.2',
		'-rc',
		'-BETA0',      # suffix matching is case insensitive
		'-RC2',
	])
	def test_prerelease_equals_final_release(self, suffix: str):
		'''A pre-release must compare equal to its final release.'''
		assert runner._parse_version(f'5.5.0{suffix}') == runner._parse_version('5.5.0')

	@pytest.mark.parametrize(('version_string', 'expected'), [
		('5.5.0', 5_005_000),
		('5.4.1', 5_004_001),
		('6.0.2', 6_000_002),
		('5.5', 5_005_000),
		('5', 5_000_000),
		('5.5.0-beta0', 5_005_000),
		('5.5.0-beta0+', 5_005_000),
		('4.0.0-beta', 4_000_000),
		('4.5.0-beta.3', 4_005_000),
	])
	def test_encoding_is_xyyyzzz(self, version_string: str, expected: int):
		assert runner._parse_version(version_string) == expected

	def test_repairs_done_marker_is_ignored(self):
		assert runner._parse_version('5.5.0+') == runner._parse_version('5.5.0')
		assert runner._parse_version('5.5.0-beta0+') == runner._parse_version('5.5.0-beta0')

	def test_ordering_is_preserved_across_prereleases(self):
		'''Pre-release suffixes must not reorder versions relative to each other.'''
		assert runner._parse_version('5.4.1') < runner._parse_version('5.5.0-beta0')
		assert runner._parse_version('5.5.0-beta0') < runner._parse_version('5.6.0')

	def test_unknown_suffix_is_not_silently_accepted(self):
		'''Only -alpha/-beta/-rc are stripped; anything else is a packaging error we surface.'''
		with pytest.raises(ValueError):
			runner._parse_version('5.5.0-nightly')


class TestGetPreviousVersion:
	@pytest.fixture
	def version_info(self, tmp_path):
		return str(tmp_path / runner.VERSION_INFO_FILE)

	def test_missing_file_runs_all_repairs(self, version_info: str):
		assert runner.get_previous_version(version_info) == (0, True)

	def test_empty_file_runs_all_repairs(self, version_info: str, monkeypatch):
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		with open(version_info, 'w') as f:
			f.write('  \n')
		assert runner.get_previous_version(version_info) == (0, True)

	@pytest.mark.parametrize(('recorded', 'app_version'), [
		('5.5.0-beta0+', '5.5.0'),        # upgraded from a beta to its final release
		('5.5.0+', '5.5.0-beta0'),        # downgraded from the release back to a beta
		('5.5.0-beta0+', '5.5.0-beta0'),  # same beta restarted
		('5.5.0-beta0+', '5.5.0-beta1'),  # a later beta of the same version
		('4.0.0-beta+', '4.0.0'),         # suffix with no trailing digits
		('4.5.0-beta.3+', '4.5.0'),       # dotted pre-release form
	])
	def test_completed_repairs_are_not_rerun(self, version_info: str, monkeypatch, recorded: str, app_version: str):
		monkeypatch.setenv('APP_VERSION', app_version)
		with open(version_info, 'w') as f:
			f.write(recorded)

		(previous_version, repairs_pending) = runner.get_previous_version(version_info)

		assert previous_version == runner._parse_version(app_version)
		assert repairs_pending is False

	def test_missing_marker_keeps_repairs_pending(self, version_info: str, monkeypatch):
		'''Without the trailing '+' the previous run never finished, so repairs must run.'''
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		with open(version_info, 'w') as f:
			f.write('5.5.0-beta0')

		assert runner.get_previous_version(version_info) == (5_005_000, True)

	def test_upgrade_keeps_repairs_pending(self, version_info: str, monkeypatch):
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		with open(version_info, 'w') as f:
			f.write('5.4.1+')

		assert runner.get_previous_version(version_info) == (5_004_001, True)


class TestMain:
	'''The real repair modules talk to the database, so these tests always run against a
	throwaway repair directory loaded straight from disk.
	'''

	@pytest.fixture
	def storage(self, tmp_path, monkeypatch):
		monkeypatch.setenv('APP_PERSISTENT_STORAGE', str(tmp_path))
		return tmp_path

	@pytest.fixture
	def fake_repairs(self, storage, monkeypatch):
		repair_dir = storage / 'repair'
		repair_dir.mkdir()
		monkeypatch.setattr(runner, 'REPAIR_DIR', str(repair_dir))

		def load(name: str, _package: str):
			filename = name.removeprefix('.repair.') + '.py'
			spec = importlib.util.spec_from_file_location(name, repair_dir / filename)
			assert spec is not None and spec.loader is not None
			mod = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(mod)
			return mod

		monkeypatch.setattr(runner, 'import_module', load)
		return repair_dir

	def test_prerelease_version_completes_and_records_marker(self, storage, fake_repairs, monkeypatch, capsys):
		'''Regression: a pre-release APP_VERSION used to crash with ValueError.'''
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		(storage / runner.VERSION_INFO_FILE).write_text('5.5.0-beta0')

		runner.main()

		assert 'Repairs completed.' in capsys.readouterr().out
		assert (storage / runner.VERSION_INFO_FILE).read_text() == '5.5.0-beta0+'
		assert not (storage / runner.PARTIAL_REPAIR_FILE).exists()

	def test_release_skips_repairs_completed_by_its_beta(self, storage, fake_repairs, monkeypatch, capsys):
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		runner.main()
		capsys.readouterr()

		monkeypatch.setenv('APP_VERSION', '5.5.0')
		runner.main()

		assert 'No repairs are required.' in capsys.readouterr().out

	def test_pending_repair_runs_with_the_previous_version(self, storage, fake_repairs, monkeypatch, capsys):
		'''A repair newer than the recorded version runs, and run() receives that version.'''
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		(storage / runner.VERSION_INFO_FILE).write_text('5.4.1+')
		marker = storage / 'ran.txt'
		(fake_repairs / 'repair5005000_date20260101000000.py').write_text(dedent(f'''
			def run(previous_version):
				with open({str(marker)!r}, 'w') as f:
					f.write(str(previous_version))
		'''))

		runner.main()

		assert marker.read_text() == str(runner._parse_version('5.4.1'))
		assert (storage / runner.VERSION_INFO_FILE).read_text() == '5.5.0-beta0+'

	def test_skipped_repair_is_never_imported(self, storage, fake_repairs, monkeypatch, capsys):
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		(storage / runner.VERSION_INFO_FILE).write_text('5.4.1+')
		(fake_repairs / 'repair5005000_date20260101000000.py').write_text('raise AssertionError("must not import")')
		(storage / runner.REPAIR_SKIP_FILE).write_text('repair5005000_date20260101000000.py\n')

		runner.main()

		assert 'listed in repair.info' in capsys.readouterr().out

	def test_failed_repair_leaves_version_unmarked(self, storage, fake_repairs, monkeypatch):
		'''A crashing repair must propagate and must not record the version as repaired.'''
		monkeypatch.setenv('APP_VERSION', '5.5.0-beta0')
		(storage / runner.VERSION_INFO_FILE).write_text('5.4.1+')
		(fake_repairs / 'repair5005000_date20260101000000.py').write_text(dedent('''
			def run(_previous_version):
				raise RuntimeError('boom')
		'''))

		with pytest.raises(RuntimeError, match='boom'):
			runner.main()

		assert (storage / runner.VERSION_INFO_FILE).read_text() == '5.4.1+'
