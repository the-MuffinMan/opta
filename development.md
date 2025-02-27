Setup
=====
```
pip install pipenv
pipenv install --dev
pipenv shell
export PYTHONPATH=$(pwd)
```

Run via `python ./opta/cli.py`

Run Tests
=========
```
make test
```

Packaging
=========
```
make build-binary
```

Publishing
==========
- Create a new release on Github with a new tag (0.<x>.<y>)
- This will trigger the `package` github action, which creates the binary and uploads it to S3
- Validate the binary by running some manual tests
- Update the `latest` file in S3 to point to the new release in the S3 bucket
- Update the docs website to point to this latest release
