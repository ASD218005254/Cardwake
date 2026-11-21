#!/bin/sh
# Cross-compile the portable Windows EXE (works on Linux/macOS/Windows with Go installed)
set -e
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -H=windowsgui" -o Cardwake.exe .
echo "Built Cardwake.exe"
