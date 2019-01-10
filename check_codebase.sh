#!/bin/bash

if [ -n "$1" ]; then
       	if [ "$1" = "--help" ] || [ "$1" = "?" ] || [ "$1" = "help"; then
		echo "usage: check_codebase.sh <pyver>"
		echo "   pyver: optional python command to run (instead of python)"
		exit
	fi
fi

pycmd="python3"

if [ $1 ]; then
	pycmd=$1
fi

echo "Checking health of argus code-base. Please wait..."

cur_date=`date`
echo "Health check: $cur_date" > argus_health.txt

# flake8 broken in py 3.6
# echo "$pycmd -m flake8..."
# echo "-----------------------------" >> argus_health.txt
# echo "Running flake8 with pycmd: $pycmd" >> argus_health.txt
# echo "-----------------------------" >> argus_health.txt
# $pycmd -m flake8 --ignore E501,E702,F401,F811,F812,F822,F823,F831,F841,N8,C9 --builtins="function" argus.py >> argus_health.txt 2>&1
# $pycmd -m flake8 --ignore E501,E702,F401,F811,F812,F822,F823,F831,F841,N8,C9 --builtins="function" src/* >> argus_health.txt 2>&1

echo "$pycmd -m pycodestyle..."
echo "-----------------------------" >> argus_health.txt
echo "Running pycodestyle with pycmd: $pycmd" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt
$pycmd -m pycodestyle --ignore=E501 argus.py >> argus_health.txt 2>&1
$pycmd -m pycodestyle --ignore=E501 src/ >> argus_health.txt 2>&1

echo "$pycmd -m pylint..."
echo "-----------------------------" >> argus_health.txt
echo "Running pylint with pycmd: $pycmd" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt

# Disabling 0602 and 1121 due to false positives / bugs with the linters code on the latter
$pycmd -m pylint --disable=all --enable=E,F --disable=E0602,E1121 argus.py >> argus_health.txt 2>&1
$pycmd -m pylint --disable=all --enable=E,F --disable=E0602,E1121 src/ >> argus_health.txt 2>&1

echo "$pycmd -m mypy --ignore-missing-imports"
echo "-----------------------------" >> argus_health.txt
echo "Running mypy with pycmd: $pycmd" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt
$pycmd -m mypy --ignore-missing-imports --strict-optional argus.py >> argus_health.txt 2>&1

echo 'results written to argus_health.txt'
