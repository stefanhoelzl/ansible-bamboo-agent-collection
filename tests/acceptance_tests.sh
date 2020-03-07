#/bin/bash
set -ex
cd `dirname $0`/env

# cleanup
git clean -fdx

# prepare server application data
tar -xzvf server/init-data.tar.gz -C server

# ansible cleanup and preperation
mkdir -p results
cp playbook.yml ansible/project/playbook.yml
../../build.sh
ansible-galaxy collection install ../../release/stefanhoelzl-bamboo_agent* -p ./ansible/project/collections
ANSIBLE_COLLECTIONS_PATHS=./ansible/project/collections ansible-playbook playbook.yml --syntax-check

# run test environment
docker-compose down
docker-compose up --build --abort-on-container-exit
docker-compose logs ansible > results/ansible.out
docker-compose down

# check results
python3 check_results.py

# successfully finished when arrived here
echo "acceptance tests finished successfully"
