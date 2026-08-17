#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import os
import re
from importlib import import_module

REPAIR_DIR = 'context_chat_backend/repair'
VERSION_INFO_FILE = 'version.info'
REPAIR_SKIP_FILE = 'repair.info'
PARTIAL_REPAIR_FILE = 'partial_repair.tmp'


def _parse_version(version_string: str) -> int:
	'''Convert a version string like "X.Y.Z" or "X.Y.Z+" to an integer XYYYZZZ.'''
	clean = version_string.rstrip('+')
	splits = clean.split('.')
	major = int(splits[0]) if splits else 0
	minor = int(splits[1]) if len(splits) > 1 else 0
	patch = int(splits[2]) if len(splits) > 2 else 0
	return major * 1_000_000 + minor * 1_000 + patch


def get_previous_version(version_info_path: str) -> tuple[int, bool]:
	'''
	'+' at the end of the version indicates that repairs have been run.
	A return of (0, True) means no previous version is known, so all repairs
	are considered pending and will run.
	The repairs are idempotent so re-running them does not cause any issue.
	'''
	if not os.path.exists(version_info_path):
		return (0, True)

	try:
		with open(version_info_path) as f:
			version_string = f.read().strip()
	except OSError as e:
		print(
			f'Warning: could not read {version_info_path}, assuming no previous version was installed: {e}',
			flush=True,
		)
		return (0, False)

	if not version_string:
		return (0, True)

	repairs_pending = not (
		version_string.endswith('+')
		and _parse_version(version_string) == _parse_version(os.environ['APP_VERSION'])
	)

	return (_parse_version(version_string), repairs_pending)


def get_skipped_repairs(persistent_storage_path: str) -> set[str]:
	repair_info_path = os.path.join(persistent_storage_path, REPAIR_SKIP_FILE)
	if not os.path.exists(repair_info_path):
		return set()

	try:
		with open(repair_info_path) as f:
			return {line.strip() for line in f if line.strip()}
	except OSError as e:
		print(f'Warning: could not read {repair_info_path}, no repairs will be skipped: {e}', flush=True)
		return set()


def main():
	'''
	Run repairs that have not been run before.
	Repair files can either have no functions or a run() function.
	To skip a repair, add its filename to repair.info in the persistent storage.
	'''
	print('Running repairs...', flush=True)

	persistent_storage_path = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
	version_info_path = os.path.join(persistent_storage_path, VERSION_INFO_FILE)
	partial_repair_path = os.path.join(persistent_storage_path, PARTIAL_REPAIR_FILE)

	try:
		all_filenames = os.listdir(REPAIR_DIR)
	except OSError as e:
		print(f'Error: could not list repair directory to get all the eligible repairs: {e}', flush=True)
		raise
	repair_filenames = sorted(f for f in all_filenames if f.startswith('repair') and f.endswith('.py'))

	(previous_app_version, repairs_pending) = get_previous_version(version_info_path)

	if not repairs_pending:
		print('No repairs are required.', flush=True)
		return

	skipped_repairs = get_skipped_repairs(persistent_storage_path)

	try:
		with open(partial_repair_path) as f:
			partial_repairs = {line.strip() for line in f if line.strip()}
	except FileNotFoundError:
		partial_repairs = set()
	except OSError as e:
		print(f'Warning: could not read {partial_repair_path}, all pending repairs will be re-run: {e}', flush=True)
		partial_repairs = set()

	for repair_filename in repair_filenames:
		pattern = re.compile(r'^repair(\d+)_date\d+\.py$')
		matches = pattern.match(repair_filename)
		if not matches:
			print(f'Ignoring invalid repair file: {repair_filename}', flush=True)
			continue

		introduced_version = int(matches.group(1))

		if introduced_version < previous_app_version:
			print(f'No repairs to run for version {introduced_version}.', flush=True)
			continue

		if repair_filename in skipped_repairs:
			print(f'Skipping repair {repair_filename} (listed in repair.info).', flush=True)
			continue

		if repair_filename in partial_repairs:
			print(f'Skipping repair {repair_filename} (already completed in partial run).', flush=True)
			continue

		print(f'Running repair {repair_filename}...', flush=True, end='')

		mod = import_module(f'.repair.{repair_filename[:-3]}', 'context_chat_backend')
		if hasattr(mod, 'run'):
			try:
				mod.run(previous_app_version)
			except Exception:
				print(
					'failed.\n'
					'The app will not continue further until this repair step succeeds, '
					'or is skipped through the method described in https://github.com/nextcloud/context_chat_backend/#repair \n'  # noqa: E501
					'If not skipped, it will be tried again in the next app startup.',
					flush=True,
				)
				raise

		try:
			with open(partial_repair_path, 'a') as f:
				f.write(repair_filename + '\n')
		except OSError as e:
			print(f'Warning: could not write to {partial_repair_path}: {e}', flush=True)

		print('completed.', flush=True)

	try:
		if os.path.exists(partial_repair_path):
			os.unlink(partial_repair_path)
	except OSError as e:
		print(f'Warning: could not remove {partial_repair_path}: {e}', flush=True)

	try:
		with open(version_info_path, 'w') as f:
			f.write(os.environ['APP_VERSION'] + '+')
	except OSError as e:
		print(f'Error: could not write {version_info_path}: {e}', flush=True)
		return

	print('Repairs completed.', flush=True)


if __name__ == '__main__':
	main()
