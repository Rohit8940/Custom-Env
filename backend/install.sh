#!/bin/bash
echo 'Creating Conda environment...'
conda create -y -n offline_env python=3.9
conda activate offline_env || source activate offline_env
pip install --no-index --find-links=offline_wheels \
    flask==3.1.0 \
    Werkzeug==3.1.3 \
    Jinja2==3.1.6 \
    itsdangerous==2.2.0 \
    click==8.2.0 \
    blinker==1.9.0 \
    importlib-metadata==8.7.0 \
    asgiref==3.8.1 \
    python-dotenv==1.1.0
