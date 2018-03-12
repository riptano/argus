#!/bin/bash

echo "Checking health of argus code-base. Please wait..."

cur_date=`date`
echo "Health check: $cur_date" > argus_health.txt

echo "flake8..."
echo "-----------------------------" >> argus_health.txt
echo "Running flake8" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt
python3 -m flake8 --ignore E501,E702,F401,F811,F812,F822,F823,F831,F841,N8,C9 argus.py >> argus_health.txt 2>&1
python3 -m flake8 --ignore E501,E702,F401,F811,F812,F822,F823,F831,F841,N8,C9 src/* >> argus_health.txt 2>&1

echo 'pycodestyle...'
echo "-----------------------------" >> argus_health.txt
echo "Running pycodestyle" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt
python3 -m pycodestyle --ignore=E501 argus.py >> argus_health.txt 2>&1
python3 -m pycodestyle --ignore=E501 src/ >> argus_health.txt 2>&1

echo 'pylint...'
echo "-----------------------------" >> argus_health.txt
echo "Running pylint" >> argus_health.txt
echo "-----------------------------" >> argus_health.txt
python3 -m pylint --disable=all --enable=E,F argus.py >> argus_health.txt 2>&1
python3 -m pylint --disable=all --enable=E,F src/ >> argus_health.txt 2>&1

echo 'results written to argus_health.txt. Opening with less.'
less argus_health.txt
