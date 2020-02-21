# Benchmark Docker Manager


Run experiments on queued docker images as reported by the evaluation Controller.


### Configuration


Make sure all environmental variables are valid for your experiment. You can set up them in [this .env file](container_config.env)! Below you can find a description of each variable.

```bash
# The period between subsequent executions of the manager, in seconds
EXECUTION_FREQUENCY_SECONDS=30
# The URI for the controller (including http://) or `host.docker.internal` if you are running locally on a Mac
# Will NOT work with 127.0.0.1!
CONTROLLER_URI=host.docker.internal
# The endpoint for submitting results to the controller
CONTROLLER_RESULT_ENDPOINT=/result
# The endpoint for retreiving schedule from the controller
CONTROLLER_SCHEDULE_ENDPOINT=/schedule
# The endpoint for submitting updates to the controller
CONTROLLER_STATUS_ENDPOINT=/status_update
# The maximum duration of the benchmark, after which the benchmark container can terminate 
BENCHMARK_HARD_TIMEOUT_SECONDS=7200
# The absolut path for the dataset on the host machine 
HOST_DATASET_PATH=/Users/blabla/debs-2020-challenge-manager/dataset
# The absolute path for of the log folder contained in this directory. Using another directory will NOT work without changing the volumes in docker-compose.yml
HOST_RESULTS_PATH=/Users/blabla/debs-2020-challenge-manager/logs
# Paths local to the benchmark grader container, no need to change
BENCHMARK_CONTAINER_DATASET_PATH=/dataset
BENCHMARK_CONTAINER_RESULTS_BASE_PATH=/results
```
### Execution


Run with:
`docker-compose up --build`
After the controller server is up.