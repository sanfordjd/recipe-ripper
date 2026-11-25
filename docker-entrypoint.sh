#!/bin/sh
set -eu

# Hosted Postgres needs no local database mount. Browser scratch files use /tmp.
if [ -n "${DATABASE_URL:-${POSTGRES_URL:-}}" ]
then
    install -d -m 700 -o recipe -g recipe /tmp/recipe-home
    export HOME=/tmp/recipe-home
else
    if [ "${VERCEL:-}" = "1" ]
    then
        echo "Connect hosted Postgres and set DATABASE_URL before starting on Vercel." >&2
        exit 1
    fi
    if [ "${DATABASE_PATH:-}" != "/var/data/recipes.sqlite3" ]
    then
        echo "SQLite hosting requires DATABASE_PATH=/var/data/recipes.sqlite3." >&2
        exit 1
    fi
    if [ -L /var/data ]
    then
        echo "The data mount must be a directory, not a symbolic link." >&2
        exit 1
    fi
    install -d -m 700 -o recipe -g recipe /var/data
    for recipe_file in /var/data/recipes.sqlite3 /var/data/recipes.sqlite3-journal /var/data/recipes.sqlite3-wal /var/data/recipes.sqlite3-shm
    do
        if [ -L "$recipe_file" ]
        then
            echo "Recipe database files must not be symbolic links." >&2
            exit 1
        fi
        if [ -f "$recipe_file" ]
        then
            chown recipe:recipe "$recipe_file"
            chmod 600 "$recipe_file"
        fi
    done
    export HOME=/home/recipe
fi

export TMPDIR=/tmp
export USER=recipe
export LOGNAME=recipe
exec gosu recipe "$@"
