#!/bin/bash

if [ $1 = "-?" ]; then
	echo "usage: check_codebase.sh <pyver>"
	echo "   pyver: optional python command to run (instead of python)"
	exit
fi

pycmd="python"

if [ $1 ]; then
	pycmd=$1
fi

echo "Checking health of argus code-base. Please wait..."

cur_date=`date`
echo "Health check: $cur_date" > argus_health.txt

echo "$pycmd -m flake8..."
echo "-----------------------------" >> argus_health.txt
echo "Running flake8 with pycmd: $pycmd" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt
$pycmd -m flake8 --ignore E501,E702,F401,F811,F812,F822,F823,F831,F841,N8,C9 argus.py >> argus_health.txt 2>&1
$pycmd -m flake8 --ignore E501,E702,F401,F811,F812,F822,F823,F831,F841,N8,C9 src/* >> argus_health.txt 2>&1

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
$pycmd -m pylint --disable=all --enable=E,F argus.py >> argus_health.txt 2>&1
$pycmd -m pylint --disable=all --enable=E,F src/ >> argus_health.txt 2>&1

echo 'results written to argus_health.txt. Opening with less.'
less argus_health.txt
