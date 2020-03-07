#/bin/bash
set -x

# docker cleanup
docker kill testenv_agent_1 testenv_server_1 testenv_ansible_1
docker rm testenv_agent_1 testenv_server_1 testenv_ansible_1
docker network rm testenv_internal testenv_default

set -e

# server cleanup
rm -Rf server/data
tar -xzvf server/init-data.tar.gz -C server

# ansible cleanup and preperation
rm -rf ansible/project/library results
mkdir -p ansible/project/library ansible/project/results
cp ../bamboo-agent-configuration.py ansible/project/library

# run test environment
docker-compose up --build --abort-on-container-exit
docker-compose logs ansible > results/ansible.out

# check results
python3 check_results.py
