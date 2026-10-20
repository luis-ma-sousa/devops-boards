#!/usr/bin/env bash
# Double-click this file in Finder to start Boards on a Mac.
cd "$(dirname "$0")"
./run.sh "$@"
status=$?
if [ $status -ne 0 ]; then
  echo
  read -r -p "Something went wrong (see above). Press Enter to close this window." _
fi
exit $status
