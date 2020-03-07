#!/bin/bash
set -ex
cd `dirname $0`

BUILD_BASE=$PWD/build
OUTPUT_BASE=$PWD/release

# cleanup
rm -rf $BUILD_BASE
mkdir -p $OUTPUT_BASE $BUILD_BASE

# copy collection files
cp -R docs plugins galaxy.yml LICENSE README.md $BUILD_BASE

# build collection
cd $BUILD_BASE
ansible-galaxy collection build --force --output-path $OUTPUT_BASE
