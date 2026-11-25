#!/bin/sh
set -eu

# Initialize the mounted disk, then run the app and browser as an ordinary user.
if [ "${DATABASE_PATH:-}" != "/var/data/recipes.sqlite3" ]
then
    echo "This hosting package requires DATABASE_PATH=/var/data/recipes.sqlite3." >&2
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
export USER=recipe
export LOGNAME=recipe
exec gosu recipe "$@"
