#!/usr/bin/env sh
#
# SPDX-FileCopyrightText: 2024 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# pre-release suffixes (-alpha*, -beta*, -rc*) are stripped, like in the repair runner
version=${APP_VERSION%%-*}
parts=(${version//./ })
repair_filename="repair${parts[0]}$(printf %03d ${parts[1]})$(printf %03d ${parts[2]})_date$(date +%Y%m%d%H%M%S).py"

echo "Generating repair script: $repair_filename"
read -p "Confirm to create the repair script? [Y/n] " confirm
if [[ ! $confirm =~ ^[Yy]*$ ]]; then
	echo "Aborted."
	exit 1
fi

touch "context_chat_backend/repair/$repair_filename"
