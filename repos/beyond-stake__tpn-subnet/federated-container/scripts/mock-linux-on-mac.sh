#!/bin/sh

# POSIX utility functions that mimic Linux commands with static mock data
# Usage: . /path/to/dev-utils.sh

# Mimics 'free' command - shows memory information
free() {
    if [ "$1" = "-g" ]; then
        echo "              total       used       free     shared    available"
        echo "Mem:             16          8          8          0          8"
        echo "Swap:             8          2          6"
    else
        echo "              total        used        free      shared     available"
        echo "Mem:       16777216     8388608     8388608           0     8388608"
        echo "Swap:      8388608     2097152     6291456"
    fi
}

# Mimics 'cat /proc/swaps' - shows swap file information
cat() {
    if [ "$1" = "/proc/swaps" ]; then
        echo "Filename				Type		Size	Used	Priority"
        echo "/var/vm/swapfile0                      file		8388608	2097152	-2"
    else
        command cat "$@"
    fi
}

# Mimics 'df -BG' - shows disk space in gigabytes
df() {
    # Check if -BG flag is present using case statement (POSIX compliant)
    case "$*" in
        *"-BG"*)
            echo "Filesystem     1G-blocks  Used Available Use% Mounted on"
            echo "/dev/disk1s1       500G  200G       20G  91% /"
            ;;
        *)
            command df "$@"
            ;;
    esac
}
