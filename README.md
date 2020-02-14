# Benchmark Docker Manager
Run experiments on queued docker images, collected by DEBS-API Scheduler.

#### Basic usage:

Make sure all environmental variables are valid for your experiment:

You can set up them in [this .env file](server_app/.env)!

  `Important!` Adjust here timeouts and absolute path for your data.
  `HOST_DATASET_FOLDER`
  `HOST_LOG_FOLDER`
  and the Timeouts.

<br>

`Additional variables` can be set in [main docker-compose file](./docker-compose-manager.yml)

  EXECUTION_FREQUENCY_SECONDS, controller endpoint URI, and default controller API routes that are queried.

  `Important!` make sure the controller URI is set correctly.

<br>
Run with:
`docker-compose -f docker-compose-manager.yml up --build`
After API server is up.
