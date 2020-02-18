import docker
import logging
from logging.handlers import TimedRotatingFileHandler
import subprocess
import datetime
import sys, os
import yaml
import json
import re
from collections import OrderedDict
import dataset
import time
import requests
#mysql connector
import pymysql
pymysql.install_as_MySQLdb()


LOG_FORMAT='%(asctime)s - %(name)s - %(threadName)s -  %(levelname)s - %(message)s'
LOG_FILENAME = 'compose_manager.log'
LOG_LEVEL=logging.DEBUG
GRADER_CONTAINER_LOG_EXTENSION = '_grader_container.log'
SOLUTION_CONTAINER_LOG_EXTENSION = '_solution_container.log'
CONTROLLER_URI = os.getenv("CONTROLLER_URI")
SCHEDULE_ENDPOINT = os.getenv("CONTROLLER_SCHEDULE_ENDPOINT", default= '/schedule')
RESULT_ENDPOINT = os.getenv("CONTROLLER_RESULT_ENDPOINT", default='/result')
STATUS_ENDPOINT = os.getenv("CONTROLLER_STATUS_ENDPOINT", default="/status_update")
MAX_RETRY_ATTEMPTS = 3
CONTAINER_LOGS_PATH='../logs'
MANAGER_LOGS_PATH = "../manager_logs"
BENCHMARK_DOCKER_COMPOSE_TEMPLATE='docker-compose-template.yml'
EXEUCTION_FREQUENCY_SECONDS = int(os.getenv("EXECUTION_FREQUENCY_SECONDS", default=30))
SOLUTION_CONTAINER_NAME_PREFIX = 'solution-app-'
GRADER_CONTAINER_NAME = 'debs-2020-grader'
# Docker image IDs are strings with the format team/image
# This variable chooses which of the two parts will be used for identification in manager executions of the image
DOCKER_IMAGE_IDENTIFIER = 'team' 

def extractDockerImageID(image):
    '''Extract either of the team or the image part out of a docker image ID of the form "team/image"
    Uses the global variable DOCKER_IMAGE_IDENTIFIER to perform the selection
    '''
    if DOCKER_IMAGE_IDENTIFIER == 'team':
        index = 0
    elif DOCKER_IMAGE_IDENTIFIER == 'image':
        index = 1
    else:
        raise ValueError('Unknown DOCKER_IMAGE_IDENTIFIER: %s' % DOCKER_IMAGE_IDENTIFIER)
    return image.split('/')[index]


class Manager:

    def __init__(self):
        # used to encode datetime objects
        json.JSONEncoder.default = lambda self,obj: (obj.isoformat() if isinstance(obj, datetime.datetime) else None)
        self.images = []
        self.retry_attempts = {} # for each image

        self.logger = self.create_logs()

        self.logger.info("Manager will wait %s seconds between executions" % EXEUCTION_FREQUENCY_SECONDS)

        self.endpoint = CONTROLLER_URI
        if not self.endpoint:
            raise ValueError("Please specify CONTROLLER_URI!")

        # if Mac OS and running on the same machine with the frontend controller
        # specify (CONTROLLER_URI: host.docker.internal)
        if "docker" in self.endpoint:
            self.endpoint = 'http://' + self.endpoint + ":8080"
        self.logger.debug("Controller URI: %s" % self.endpoint)

    def create_logs(self):
            if not os.path.exists(MANAGER_LOGS_PATH):
                os.makedirs(MANAGER_LOGS_PATH)
            logging.basicConfig(format=LOG_FORMAT,
                                level=LOG_LEVEL,
                                handlers=[TimedRotatingFileHandler("%s/%s" % (MANAGER_LOGS_PATH, LOG_FILENAME), when="midnight", interval=1),
                                logging.StreamHandler()])
            logger = logging.getLogger()
            return logger

    def find_container_ip_addr(self, container_name):
        '''Helper to retrieve IP address of container
        '''
        info = subprocess.check_output(['docker', 'inspect', container_name])
        # parsing nested json from docker inspect
        ip = list(json.loads(info.decode('utf-8'))[0]["NetworkSettings"]["Networks"].values())[0]["IPAddress"]
        print("%s container ip is: %s" % (container_name, ip))
        return ip

    def execute(self, cmd):
        '''Generator function that executes an external command as a subprocess and return its stdout
        Sets the benchmark_return_code equal to the command return code
        '''
        popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        for stdout_line in iter(popen.stdout.readline, ""):
            yield stdout_line
        popen.stdout.close()
        return_code = popen.wait()
        self.benchmark_return_code = return_code
        if return_code:
            self.logger.info("Benchmark execution '%s' done executing with exit code: %s" % (cmd, return_code))

    def create_docker_compose_file(self, image, container):
        '''Create a new docker-compose.yml for the benchmark execution based on the template file and the settings
        '''
        self.logger.info("Creating docker-compose with image: '%s' and container name: '%s'" % (image, container))
        BENCHMARK_HARD_TIMEOUT_SECONDS = int(os.getenv('BENCHMARK_HARD_TIMEOUT_SECONDS'))
        BENCHMARK_CONTAINER_DATASET_PATH = os.getenv('BENCHMARK_CONTAINER_DATASET_PATH')
        HOST_DATASET_PATH = os.getenv('HOST_DATASET_PATH')
        HOST_BENCHMARK_LOGS_PATH = os.getenv('HOST_BENCHMARK_LOGS_PATH')
        BENCHMARK_CONTAINER_RESULTS_BASE_PATH = os.getenv('BENCHMARK_CONTAINER_RESULTS_BASE_PATH')
        with open(BENCHMARK_DOCKER_COMPOSE_TEMPLATE) as f:
            dockerConfig = yaml.safe_load(f)
        solutionConfig = dockerConfig["services"]["solution"]
        solutionConfig["container_name"] = container
        solutionConfig["image"] = image

        graderConfig = dockerConfig["services"]["grader"]
        graderConfig["container_name"] = GRADER_CONTAINER_NAME
        graderConfig["environment"]["HARD_TIMEOUT_SECONDS"] = BENCHMARK_HARD_TIMEOUT_SECONDS
        graderConfig["environment"]["DATASET_PATH"] = BENCHMARK_CONTAINER_DATASET_PATH
        fullContainerResultsPath = BENCHMARK_CONTAINER_RESULTS_BASE_PATH + '/' + extractDockerImageID(image)
        self.logger.info('Results for %s will be stored in %s', image, fullContainerResultsPath)
        graderConfig["environment"]["RESULTS_PATH"] = fullContainerResultsPath
        graderConfig["volumes"][0] = '%s:%s' % (HOST_DATASET_PATH, BENCHMARK_CONTAINER_DATASET_PATH)
        graderConfig["volumes"][1] = '%s:%s' % (HOST_BENCHMARK_LOGS_PATH, BENCHMARK_CONTAINER_RESULTS_BASE_PATH)

        with open('docker-compose.yml', 'w') as f:
            yaml.dump(dockerConfig, f, default_flow_style=False)
        self.logger.info("docker-compose.yml benchmark configuration file saved")

    def get_images(self):
        '''Retrieve the updated image URLs from the controller.
        '''
        updated_images = []
        response = requests.get(self.endpoint + SCHEDULE_ENDPOINT)
        self.logger.info("Scheduler answer status %s " % response.status_code)

        if (response.status_code == 403):
            self.logger.error("Manger can't access remote server. FORBIDDEN %s " % response.status_code)
            return []

        try:
            images = response.json()
        except json.decoder.JSONDecodeError as e:
                self.logger.info(" Check if the front-end server is reachable! Cannot retrieve JSON response.")
                self.logger.error(" Got error %s " % e)
                images = {}

        for image, status in images.items():
            if status == 'updated':
                try:
                    updated_images.append(image)
                    self.post_message(STATUS_ENDPOINT, {image:"Queued"})
                except IndexError:
                    self.logger.error('Incorrectly specified image encountered. Format is {team_repo/team_image}')
                    continue
        return updated_images

    def save_container_logs(self, cmd, docker_image, extension):
        '''Execute a command and store its output in a log file corresponding to the image name.
        '''
        imageKey =  extractDockerImageID(docker_image)
        path = CONTAINER_LOGS_PATH + imageKey
        filename = path + "/" + imageKey + extension
        if not os.path.exists(path):
            os.makedirs(path)
        with open(filename, "w+") as f:
            p = subprocess.Popen(cmd, shell=True, universal_newlines=True, stdout=f, stderr=subprocess.STDOUT)
            p.wait()

    def process_result(self, docker_img_name, image_tag):
            self.logger.info("Extracting results from image: %s" % docker_img_name)
            results = self.extract_result_files(docker_img_name)
            if results:
                results['tag'] = image_tag
                results['last_run'] = datetime.datetime.utcnow().replace(microsecond=0).replace(second=0)
                results['piggybacked_manager_timeout'] = EXEUCTION_FREQUENCY_SECONDS
                self.logger.info("Results: %s" % results)
                return results
            else:
                self.logger.error("No results after benchmark run of image %s" % docker_img_name)
                return {'image': docker_img_name}

    def extract_result_files(self, docker_image):
        self.logger.info("Looking for result files...")
        imageID = extractDockerImageID(docker_image)
        executionLogsPath = CONTAINER_LOGS_PATH + '/' + imageID
        jsonFiles = [f for f in os.listdir(executionLogsPath) if f.endswith('.json')]
        if not jsonFiles:
            self.logger.warning('No json result found!')
            return {}
        if len(jsonFiles) != 1:
            self.logger.warn('Multiple result files found: ' +  jsonFiles) 
            self.logger.warn('Cleaning up...')
            for file in jsonFiles:
                os.remove(file)
            return {}

        resultsFile = executionLogsPath + '/' + jsonFiles[0]
        with open(resultsFile) as f:
            data = json.load(f)
            data['image'] = docker_image
            self.logger.info("Found results for %s: %s" % (imageID, data))
        # Rename result file XX.json to XX.json.DATETIME
        resultsFileNewName = resultsFile + '.' + datetime.datetime.utcnow().strftime('%s')
        os.rename(resultsFile, resultsFileNewName)
        self.logger.info('Archived result file as: %s', resultsFileNewName)
        return data

    def start(self):
        self.logger.info("----------------------------")
        self.logger.info("Benchmark Manager started...")
        solution_container_name = 'undefined'

        # requesting schedule
        images = self.get_images()

        try:
            subprocess.Popen(['docker', 'stop', GRADER_CONTAINER_NAME], stderr=subprocess.PIPE)
            subprocess.Popen(['docker', 'rm', GRADER_CONTAINER_NAME], stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            self.logger.debug("Cleaning up unused containers, if they are left")
            self.logger.debug("Got cleanup error: %s. Proceeding!" % e)
            pass

        self.logger.info("Current scheduled images: %s" % images)
        time.sleep(5) # not necessary but if manager rerun, sometimes first image
                      # might be too slow to establish a connection

        for solution_image in images:

            solution_container_name = SOLUTION_CONTAINER_NAME_PREFIX + extractDockerImageID(solution_image)

            try:
                self.logger.debug("Cleaning up unused client containers, if they are left")
                self.logger.debug(subprocess.check_output(['docker', 'rm', solution_container_name]))
            except Exception as e:
                self.logger.info("Got client cleanup error: %s. Proceeding!" % e)

            try:
                self.logger.info("Pulling image '%s'" % solution_image)
                self.post_message(STATUS_ENDPOINT, {solution_image: "Pulling image"})
                pullOutput = subprocess.check_output(['docker', 'pull', solution_image], stderr=subprocess.STDOUT)
                self.logger.debug('docker pull %s: %s', solution_image, pullOutput)
                self.logger.debug("Inspecting image '%s'" % solution_image)
                inspectOutput = subprocess.check_output(['docker', 'inspect', solution_image], stderr=subprocess.STDOUT)
                tag = json.loads(inspectOutput.decode('utf-8'))[0]["Id"]
                self.logger.info("Image tag is : %s" % tag)
            except Exception as e:
                self.logger.error("Error accessing image: %s: %s", solution_image, e)
                continue

            self.create_docker_compose_file(solution_image, solution_container_name)

            self.post_message(STATUS_ENDPOINT, {solution_image: "Running experiment"})

            cmd = ['docker-compose', 'up', '--build', '--abort-on-container-exit']
            for path in self.execute(cmd):
                self.logger.info(path)
                sys.stdout.flush()


            self.logger.debug("docker-compose exited")
            self.post_message(STATUS_ENDPOINT, {solution_image: "Preparing results"})

            solutionLogsCmd = 'docker logs ' + solution_container_name
            self.save_container_logs(solutionLogsCmd, solution_image, SOLUTION_CONTAINER_LOG_EXTENSION)
            graderLogsCmd = 'docker logs ' + GRADER_CONTAINER_NAME
            self.save_container_logs(graderLogsCmd, solution_image, GRADER_CONTAINER_LOG_EXTENSION)
            self.logger.debug("Container logs saved")

            self.logger.info("Image %s completed " % solution_image)
            results = self.process_result(solution_image, tag)

            if self.benchmark_return_code or not results:
                self.logger.error("docker-compose exited with code %s, results: %s", self.benchmark_return_code, results)
                retries = self.retry_attempts.get(solution_image, 0)
                if retries <= MAX_RETRY_ATTEMPTS:
                     self.retry_attempts[solution_image] = retries + 1
                     self.logger.warn('Will retry on next round')
                     self.post_message(STATUS_ENDPOINT, {solution_image: "Retrying"})
                     continue
                else:
                    self.logger.error('Image has exceeded maximum retry attempts!')

            self.logger.info("Retry attempts: %s " % self.retry_attempts)
            self.post_message(STATUS_ENDPOINT, {solution_image: "Ready"})
            self.post_message(RESULT_ENDPOINT, results)

            self.logger.info("Completed run for image: %s" % solution_image)

        self.logger.info("Evaluation complete!")
        images = []
        return

    def post_message(self, endpoint, payload):
        headers = {'Content-type': 'application/json'}
        try:
            response = requests.post(self.endpoint + endpoint, json = payload, headers=headers)
            if (response.status_code == 201):
                return {'status': 'success', 'message': 'updated'}
            else:
                return {'status': response.status_code}
        except requests.exceptions.ConnectionError as e:
            self.logger.error("Error posting payload '%s' at %s: %s", payload, endpoint, e)


if __name__ == '__main__':
    manager = Manager()
    while(True):
        manager.start()
        time.sleep(EXEUCTION_FREQUENCY_SECONDS)
