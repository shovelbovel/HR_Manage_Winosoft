#!/bin/sh
set -e

# The Firestore/Auth/Storage emulator only ever holds data in memory —
# every container restart (or an in-place emulator process reset) wipes it
# silently, which meant re-seeding by hand after every Docker hiccup. This
# persists it to a Docker-managed volume across restarts: import on start
# if a prior export exists, always export on a graceful shutdown.
#
# The export target is a SUBDIRECTORY of the mounted volume, not the mount
# point itself — firebase-tools' export does an rmdir+recreate of its
# target directory, which fails with EBUSY against a mount point (a mount
# point can't be rmdir'd, on any OS). A plain directory living inside the
# volume doesn't have that restriction.
DATA_DIR=/srv/emulator-data/export

ARGS="emulators:start --project hr-management-dev --export-on-exit=$DATA_DIR --only firestore,auth,storage"

if [ -f "$DATA_DIR/firebase-export-metadata.json" ]; then
  ARGS="$ARGS --import=$DATA_DIR"
fi

exec firebase $ARGS
