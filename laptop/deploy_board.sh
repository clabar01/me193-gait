#!/usr/bin/env bash
# Deploy the board app (unoq_app/) to the Uno Q and restart it.
#
#   laptop/deploy_board.sh             # Python side + models (after retraining)
#   laptop/deploy_board.sh --sketch    # also the sketch (reflashes the MCU:
#                                      #   power-cycle the board afterwards, see CLAUDE.md)
#   BOARD=arduino@192.168.1.173 laptop/deploy_board.sh   # if AirFour.local doesn't resolve
#
# model1.py and model2.py already copy their outputs into
# unoq_app/python/models/; this checks that copy is current before deploying.
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  "" | --sketch) ;;
  -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $1 (use --sketch or --help)" >&2; exit 2 ;;
esac

BOARD="${BOARD:-arduino@AirFour.local}"
APP="~/ArduinoApps/me193_gait"

for f in models/model1.json models/model2_rules.py; do
  if ! cmp -s "$f" "unoq_app/python/models/$(basename "$f")"; then
    echo "unoq_app/python/models/$(basename "$f") differs from $f: rerun laptop/model1.py and laptop/model2.py" >&2
    exit 1
  fi
done

files=(unoq_app/app.yaml unoq_app/python)
if [[ "${1:-}" == "--sketch" ]]; then
  files+=(unoq_app/sketch)
fi

echo "copying ${files[*]} to $BOARD:ArduinoApps/me193_gait/"
scp -q -r "${files[@]}" "$BOARD:ArduinoApps/me193_gait/"
echo "restarting me193_gait (stop + start; 'app restart' can fail with 'app is running')"
ssh "$BOARD" "timeout -k 5 120 arduino-app-cli app stop $APP; timeout -k 5 420 arduino-app-cli app start $APP"
if [[ "${1:-}" == "--sketch" ]]; then
  echo "sketch reflashed: power-cycle the board before trusting it"
fi
