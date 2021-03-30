# needed as a separate script to be able to use in github workflow after `pipenv run`
SPHINXOPTS="-W" make --directory=docs html # the -W flag treats warnings as errors to cause build failures
