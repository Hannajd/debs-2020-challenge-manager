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

SPLIT_PART = 0 # !!! of string part of dockerhub image_name.split("/")[SPLIT_PART]
# 1) for testing withing multiple containers in one docker repo
# 0) for running over multiple docker repos

# HOST = "http://127.0.0.1:8080"
LOG_FORMAT='%(asctime)s - %(name)s - %(threadName)s -  %(levelname)s - %(message)s'
LOG_FILENAME = 'compose_manager.log'
FILE_LOG_LEVEL=logging.DEBUG
STDOUT_LOG_LEVEL=logging.ERROR
GRADER_CONTAINER_LOG_EXTENSION = '_grader_container.log'
SOLUTION_CONTAINER_LOG_EXTENSION = '_solution_container.log'
CONTROLLER_URI = os.getenv("CONTROLLER_URI")
SCHEDULE_PATH = os.getenv("CONTROLLER_SCHEDULE_PATH", default= '/schedule')
RESULT_PATH = os.getenv("CONTROLLER_RESULT_PATH", default='/result')
STATUS_PATH = "/status_update"
MAX_RETRY_ATTEMPTS = 3
LOG_FOLDER_NAME = "manager_logs"
BENCHMARK_DOCKER_COMPOSE_TEMPLATE='docker-compose-template.yml'
EXEUCTION_FREQUENCY_SECONDS = int(os.getenv("EXECUTION_FREQUENCY_SECONDS", default=30))

class Manager:

    def __init__(self):
        # used to encode datetime objects
        json.JSONEncoder.default = lambda self,obj: (obj.isoformat() if isinstance(obj, datetime.datetime) else None)
        self.images = []
        self.retry_attempts = {} #for each image
        self.client_progress_status = 0 #how many scenes processed until now

        self.logger = self.create_logs()

        self.logger.info("Manager will wait %s seconds between executions" % EXEUCTION_FREQUENCY_SECONDS)

        self.endpoint = CONTROLLER_URI
        if not self.endpoint:
            raise ValueError("Please specify CONTROLLER_URI!")

        # if Mac OS and running on the same machine with the frontend controller
        # specify (CONTROLLER_URI: host.docker.internal)
        if "docker" in self.endpoint:
            self.endpoint = 'http://' + self.endpoint + ":8080"

        self.logger.debug("Controller endpoint: %s" % self.endpoint)

    def create_logs(self):
            if not os.path.exists(LOG_FOLDER_NAME):
                os.makedirs(LOG_FOLDER_NAME)
            logger = logging.getLogger()
            formatter = logging.Formatter(LOG_FORMAT)
            fileHandler = TimedRotatingFileHandler("%s/%s" % (LOG_FOLDER_NAME, LOG_FILENAME), when="midnight", interval=1)
            fileHandler.setLevel(FILE_LOG_LEVEL)
            fileHandler.setFormatter(formatter)
            streamHandler = logging.StreamHandler()
            streamHandler.setLevel(STDOUT_LOG_LEVEL)
            streamHandler.setFormatter(formatter)
            logger.addHandler(streamHandler)
            logger.addHandler(fileHandler) 
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
        '''Execute an external command as a subprocess and print its stdout in real time
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
        self.logger.info("creating docker-compose with image: %s and container: %s " % (image, container))
        with open(BENCHMARK_DOCKER_COMPOSE_TEMPLATE) as f:
            dockerConfig = yaml.safe_load(f)
        dockerConfig["services"]["client"]["container_name"] = container
        dockerConfig["services"]["client"]["image"] = image

        with open('docker-compose.yml', 'w') as f:
            yaml.dump(dockerConfig, f, default_flow_style=False)
        self.logger.info("docker-compose.yml benchmark configuration file saved")

    def get_images(self):
        '''Retrieve the updated image URLs from the controller.
        '''
        updated_images = []
        response = requests.get(self.endpoint + SCHEDULE_PATH)
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
                    self.post_status({image:"Queued"})
                except IndexError:
                    self.logger.error('Incorrectly specified image encountered. Format is {team_repo/team_image}')
                    continue
        return updated_images

    def save_container_log(self, cmd, docker_image, extension):
        '''Execute a command and store its output in a log file corresponding to the image name
        '''
        imageKey =  docker_image.split('/')[SPLIT_PART]  
        path = "../logs/" + imageKey
        filename = path + "/" + imageKey + extension
        if not os.path.exists(path):
            os.makedirs(path)
        with open(filename, "w+") as f:
            p = subprocess.Popen(cmd, shell=True, universal_newlines=True, stdout=f, stderr=subprocess.STDOUT)
            p.wait()

    def process_result(self, docker_img_name, image_tag):
            global EXEUCTION_FREQUENCY_SECONDS
            self.logger.info("Running image: %s " % docker_img_name)
            self.logger.info("Extracting results")
            team_result = self.extract_result_files(docker_img_name)
            if team_result:
                team_result['tag'] = image_tag
                team_result['last_run'] = datetime.datetime.utcnow().replace(microsecond=0).replace(second=0)
                team_result['piggybacked_manager_timeout'] = EXEUCTION_FREQUENCY_SECONDS
                self.logger.info("Sending results: %s" % team_result)
                self.client_progress_status = team_result.get("computed_scenes",0)
                return team_result
            else:
                self.logger.error("No results after becnhmark run of %s" % docker_img_name)
                return {'team_image_name': docker_img_name,'computed_scenes':0}
            sys.stdout.flush()

    def extract_result_files(self, docker_image):
        self.logger.info("Looking for log folders")
        rootdir = "./logs"
        if "logs" in os.walk(rootdir):
            pass
        else:
            rootdir = "../logs"

        path = docker_image.split('/')[SPLIT_PART]
        list_of_files = os.listdir(rootdir+"/"+path)
        # print("files", list_of_files)
        list_of_files = [i for i in list_of_files if ".json" in i]
        if not list_of_files:
            self.logger.warning('No file result.json yet')
            return {}
        fresh_log = list_of_files[0]
        # print(fresh_log)
        res_json_folder = rootdir + "/"+ path + "/"
        new_log = fresh_log.split('.')[0] + "checkedAt" + datetime.datetime.utcnow().strftime("%s") + "."+ fresh_log.split('.')[1]
        with open(rootdir + "/"+ path + "/" + fresh_log) as f:
            data = json.load(f)
            data['team_image_name'] = docker_image
            self.logger.info("Found data in %s is: %s" % (path, data))
        subprocess.check_output(['mv', res_json_folder+fresh_log, res_json_folder+new_log])
        self.logger.info("Removed result file :%s after check" % res_json_folder+new_log)
        return data

    def start(self):
        self.logger.info("----------------------------")
        self.logger.info("Benchmark Manager started...")
        grader_container_name = "benchmark-server-self.logger"
        client_container_name = "client-app-"

        # requesting schedule
        images = self.get_images()

        try:
            subprocess.Popen(['docker', 'stop', grader_container_name], stderr=subprocess.PIPE)
            subprocess.Popen(['docker', 'rm', grader_container_name], stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            self.logger.debug("Cleaning up unused containers, if they are left")
            self.logger.debug("Got cleanup error: %s. Proceeding!" % e)
            pass

        self.logger.info("Current scheduled images: %s" % images)
        time.sleep(5) # not necessary but if manager rerun, sometimes first image
                      # might be too slow to establish a connection

        for solution_image in images:
            try:
                subprocess.check_output(['docker', 'rm', client_container_name+solution_image.split("/")[SPLIT_PART]])
            except Exception as e:
                self.logger.debug("Cleaning up unused client containers, if they are left")
                self.logger.debug("Got client cleanup error: %s. Proceeding!" % e)

            try:
                self.logger.info("Pulling image '%s'" % solution_image)
                self.post_status({solution_image: "Pulling image"})
                pullOutput = subprocess.check_output(['docker', 'pull', solution_image], stderr=subprocess.STDOUT)
                self.logger.debug('docker pull %s: %s', (solution_image, pullOutput))
                self.logger.debug("Inspecting image '%s'" % solution_image)
                inspectOutput = subprocess.check_output(['docker', 'inspect', solution_image], stderr=subprocess.STDOUT)
                self.logger.debug('docker inspect %s: %s', (solution_image, inspectOutput))
                tag = json.loads(tagOutput.decode('utf-8'))[0]["Id"]
                self.logger.info("Image tag is : %s" % tag)
            except Exception as e:
                self.logger.error("Error accessing image: %s: %s" % (solution_image, e))
                continue

            container_name = client_container_name+solution_image.split("/")[SPLIT_PART]
            self.create_docker_compose_file(solution_image, container_name) #TODO change for [0] for client repo name

            self.post_status({solution_image: "Running experiment"})

            cmd = ['docker-compose', 'up', '--build', '--abort-on-container-exit']
            # real-time output
            for path in self.execute(cmd):
                # print(path, "")
                self.logger.info(path)
                sys.stdout.flush()


            self.logger.debug("docker-compose exited")
            self.post_status({solution_image: "Preparing results"})

            client_container = client_container_name+solution_image.split("/")[SPLIT_PART]

            solutionLogsCmd = 'docker logs ' + client_container
            self.save_container_log(solutionLogsCmd, solution_image, SOLUTION_CONTAINER_LOG_EXTENSION)
            graderLogsCmd = 'docker logs ' + grader_container_name
            self.save_container_log(graderLogsCmd, solution_image, GRADER_CONTAINER_LOG_EXTENSION)
            self.logger.debug("Container logs saved")

            self.logger.info("Image %s completed " % solution_image)
            team_result = self.process_result(solution_image, tag)

            if self.benchmark_return_code and self.client_progress_status == 0:
                self.logger.error("Docker-compose exited with code %s" % self.benchmark_return_code)
                self.logger.warning("Will retry on the next run")
                if self.retry_attempts.get(solution_image,0) <= MAX_RETRY_ATTEMPTS:
                     self.retry_attempts[solution_image] = self.retry_attempts.get(solution_image,0) + 1
                     self.post_status({solution_image: "Retrying"})
                     continue
                else:
                    self.retry_attempts[solution_image] = self.retry_attempt.get(solution_image,0)

            self.logger.info("retry dict is: %s " % self.retry_attempts)

            self.post_status({solution_image: "Ready"})
            self.post_result(team_result)

            self.logger.info("Completed run for %s" % solution_image)

        self.logger.info("Evaluation completed.")
        images = []
        return

    def post_result(self, payload):
        #TODO: Merge with post_status?
        headers = {'Content-type': 'application/json'}
        try:
            response = requests.post(self.endpoint + RESULT_PATH, json = payload, headers=headers)

            if (response.status_code == 201):
                return {'status': 'success', 'message': 'updated'}
            if (response.status_code == 404):
                return {'message': 'Something went wrong. No scene exist. Check if the path is correct'}
        except requests.exceptions.ConnectionError as e:
            self.logger.error("Error posting result %s: %s", (payload, e))

    def post_status(self, payload):
        headers = {'Content-type': 'application/json'}
        try:
            response = requests.post(self.endpoint + STATUS_PATH, json = payload, headers=headers)
            if (response.status_code == 201):
                return {'status': 'success', 'message': 'updated'}
            else:
                return {'status': response.status_code}
        except requests.exceptions.ConnectionError as e:
            self.logger.error("Error posting status %s: %s", (payload, e))


if __name__ == '__main__':
    manager = Manager()
    while(True):
        manager.start()
        time.sleep(EXEUCTION_FREQUENCY_SECONDS)
