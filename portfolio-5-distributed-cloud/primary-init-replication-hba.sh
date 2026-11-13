#!/bin/bash
# ApexBank Digital - Portfolio 5
# Runs once during primary initdb (docker-entrypoint-initdb.d, before 01-primary-init.sql).
# The postgres image's default pg_hba.conf only allows *replication* connections
# from localhost, so remote standbys (pg_basebackup / walreceiver) would be
# rejected. Allow the dedicated replicator role from the compose network.
set -e
echo "host    replication     replicator      all                     scram-sha-256" >> "$PGDATA/pg_hba.conf"
