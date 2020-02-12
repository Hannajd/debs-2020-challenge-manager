from flask import request, session
from flask_restful import Resource
import sqlite3
import datetime
import pandas as pd
import numpy
import csv
import sys
import os.path
import subprocess
import logging
import json
import signal
import metrics
import atexit
import time

in_file = "../dataset/in.csv"
out_file = "../dataset/out.csv"
current_scene = 0
runtime_start = None
latency = 0
overall_latency = None

if not os.path.isfile(in_file):
    print("in.csv file not found. Please put datafiles in /dataset folder")
    raise FileNotFoundError()
    #exit(1)
    #time.sleep(15)
    # pwd = os.getcwd()
    # print("pwd: ", pwd)
    # subprocess.check_output(['cd ..'])
    # subprocess.check_output(['ls dataset/'])

TOTAL_SCENES = int(subprocess.check_output(["tail", "-1", in_file]).decode('ascii').split(",")[0].split('.')[0]) + 1
try:
    out_scenes = int(subprocess.check_output(["tail", "-1", out_file]).decode('ascii').split(",")[0].split('.')[0]) + 1
except FileNotFoundError:
    out_scenes = 500

#if (TOTAL_SCENES != out_scenes) raise ValueError("Mismatch of scenes in in.csv and out.csv files. Check if amount of total scenes equal")
if current_scene != 0:
    num_rows_to_skip = current_scene*72000
    print("to skip: ", num_rows_to_skip)
    df = pd.read_csv(in_file, sep=',', header = None, names=['time', 'laser_id', 'X', 'Y', 'Z'], iterator=True, skiprows=num_rows_to_skip)
    #print(df.get_chunk(5))
    # all_rows = int(subprocess.check_output(["cat " + in_file + " | wc -l"]))
    # assert(num_rows_to_skip < all_rows)
else:
    df = pd.read_csv(in_file, sep=',', header = None, names=['time', 'laser_id', 'X', 'Y', 'Z'], iterator=True)

#TODO improve global state
log_filename = 'benchmark%s.log' % int(datetime.datetime.utcnow().strftime("%s"))

logging.basicConfig(filename='../logs/'+log_filename,
                    level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(threadName)s -  %(levelname)s - %(message)s')


class Watchdog:

    def __init__(self):
        signal.signal(signal.SIGALRM, self.handler)

        #atexit.register(self.handle_exit)

    #def handle_exit(self):
         #logging.info("Benchmark exited")
         #metrics.results(current_scene, TOTAL_SCENES, Benchmark.total_time_score)
    #signum, frame
    def handler(self, signum, frame):
          logging.info("Timeout is over!")
          BenchmarkResults.results(current_scene)
          #self.func(self.num)
          exit(137)
          #raise Exception("end of time")

    def extend(self, time):
        return signal.alarm(10)

    def reset_and_extend(self, time):
        signal.alarm(0)
        return signal.alarm(time)


watchdog = Watchdog()
timeout = int(os.getenv("BENCHMARK_GET_TIMEOUT", default=600))
watchdog.reset_and_extend(timeout)

class Benchmark(Resource):

    total_time_score = 0
    # def __init__(self, common):
    #     self.common = common
    logging.info("Timeout set to %s seconds" % timeout)

    def get(self):
        global current_scene, TOTAL_SCENES, df, runtime_start, latency, overall_latency
        if not runtime_start:
            runtime_start = datetime.datetime.utcnow()
        #timeout = int(os.getenv("BENCHMARK_GET_TIMEOUT", default=10))
        #watchdog.extend(timeout)

        #signal.alarm(10)

        if current_scene >= TOTAL_SCENES:
            if Benchmark.total_time_score == 0:
                print('trying to get overall result')
                BenchmarkResults.results(current_scene)
                logging.warning('Last scene reached. Total time is 0. No more scenes left. Please, check you detailed results now')
                filename = int(datetime.datetime.utcnow().strftime("%s"))
                os.system('mv debs.db /logs/benchmark%s.db' % filename)
                return {'message': 'Last scene reached. No more scenes left. Please, check you detailed results now',
                        'total runtime': 'An error occured when computing total runtime. Please rebuild the Benchmark server'}, 404
            else:
                logging.warning('Last scene reached. No more scenes left. Please, check you detailed results now')
                runtime_end = datetime.datetime.utcnow()
                total_runtime = runtime_end - runtime_start
                logging.info("FINAL RUNTIME: %s" % total_runtime)
                logging.info("TOTAL LATENCY: %s" % overall_latency)
                print("FINAL RUNTIME: %s" % total_runtime)
                print("TOTAL LATENCY: %s" % overall_latency)
                try:
                    logging.info("AVERAGE LATENCY: %s" % (overall_latency/current_scene))
                    print("AVERAGE LATENCY: %s" % (overall_latency/current_scene))
                except TypeError:
                    pass
                filename = int(datetime.datetime.utcnow().strftime("%s"))
                BenchmarkResults.results(current_scene)
                logging.info("saving database...")
                sys.stdout.flush()
                os.system('mv debs.db /logs/destination%s.db' % filename)
                return {'message': 'Last scene reached. No more scenes left. Please, check you detailed results now',
                        'total runtime': Benchmark.total_time_score}, 404

        current_scene +=1
        print("Requested scene %s" % current_scene)
        sys.stdout.flush()

        try:
            self.get_timestamp(current_scene)
        except sqlite3.IntegrityError:
            return {"Benchmark error": "Please restart your benchmark-server to be able to submit new results"}, 404

        result = []
        sc = df.get_chunk(72000)
        if (int(sc["time"].iloc[0]) != int(sc["time"].iloc[-1])):
            raise ValueError("scene probably has incorrect number of rows", len(sc.index))

        result = sc.to_json(orient='records')
        latency = datetime.datetime.utcnow()

        return {'scene': result}

    @classmethod
    def get_timestamp(self, number):

        conn = sqlite3.connect('debs.db')
        cursor = conn.cursor()

        query = "INSERT INTO predictions (scene, requested_at) VALUES(?,?)"
        start_time = datetime.datetime.utcnow()
        cursor.execute(query, (number, start_time))
        conn.commit()
        conn.close()

    def post(self):

        #signal.alarm(0)
        #signal.alarm(5)
        global current_scene, latency, overall_latency
        scene_latency = datetime.datetime.utcnow() - latency
        if overall_latency:
            overall_latency += scene_latency
        else: #None
            overall_latency = scene_latency
        print("Latency for scene %s was %s" % (current_scene, scene_latency))
        #timeout = int(os.getenv("BENCHMARK_POST_TIMEOUT", default=10))
        #watchdog.reset_and_extend(timeout)
        score = 0

        print('Submitted scene %s' % current_scene)
        if self.scene_exists(current_scene):
            return {'message': "Scene {} already exist.".format(current_scene)}, 400
        correct_dict = self.fetch_correct_result()
        if not correct_dict:
            return {"message": "Please request at least one scene first"}, 400
        your_dict = request.get_json()
        submission_time = datetime.datetime.utcnow()

        try:
            your_dict = {str(k):int(v) for k,v in your_dict.items()}
        except ValueError:
            return {'message': "Your result json should be in format {'object_name':'1'} with key as an object name."}, 400
        except AttributeError:
            return {'message': "Your result json is incorrect. Specify it like: {'object_name:1'}"}, 400

        print(' Correct prediction', correct_dict)
        print(' Your prediction', your_dict)
        sys.stdout.flush()
        score = 0
        score2 = 0
        score3 = 0
        if your_dict:
            #score = Benchmark.diff_dicts(correct_dict, your_dict)
            score = metrics.accuracy(correct_dict,your_dict)
            score2 = metrics.precision(correct_dict,your_dict)
            score3 = metrics.recall(correct_dict,your_dict)
            print("scene accuracy", score)
            print("scene precision", score2)
            print("scene recall", score3)

        submission_result = {'scene': current_scene, 'accuracy': score, 'precision': score2, 'recall':score3}
        try:
            self.insert(submission_result, submission_time)
        except:
            return {'message': 'An error occured while inserting the item'}, 500

        return {'Your score for this scene is ': submission_result['accuracy']}, 201

    @classmethod
    def insert(cls, result, stop_time):
        conn = sqlite3.connect('debs.db')
        cursor = conn.cursor()

        select = "SELECT requested_at FROM predictions WHERE scene=?"
        cursor.execute(select, (result['scene'],))
        start_time = cursor.fetchone()

        unix_start_time = (datetime.datetime.strptime(str(start_time[0]), "%Y-%m-%d %H:%M:%S.%f")).strftime("%s")
        unix_stop_time = stop_time.strftime("%s")
        time_diff = int(unix_stop_time) - int(unix_start_time)
        Benchmark.total_time_score += time_diff
        print('Your prediction time for this scene was %s seconds' % time_diff)

        cursor = conn.cursor()
        query = "UPDATE predictions SET accuracy=?, precision=?, recall=?, prediction_speed =?, submitted_at=? WHERE scene=?"

        cursor.execute(query, (result['accuracy'], result['precision'], result['recall'], time_diff, stop_time, result['scene']))
        conn.commit()
        conn.close()

    @classmethod
    def fetch_correct_result(cls):
        a = Benchmark.read_csv(out_file, current_scene-1)
        return Benchmark.list_to_dict(a)

    @classmethod
    def scene_exists(cls, number):
        conn = sqlite3.connect('debs.db')
        cursor = conn.cursor()

        query = "SELECT prediction_speed FROM predictions WHERE scene=?"
        cursor.execute(query, (number,))
        row = cursor.fetchone()
        conn.close()
        try:
            if row[0]:
                return True
        except:
            return False

    @classmethod
    def read_csv(cls, out_file, scene):
            with open(out_file, 'r') as f:
                reader = csv.reader(f)
                for line in reader:
                    scene_index = float(line[0])
                    if scene_index == scene:
                        return line[1:]

    @classmethod
    def list_to_dict(cls,a):

        my_dict = {}
        if not a:
            return my_dict
        for index, item in enumerate(a):
            if index % 2 == 0:
                my_dict[item] = a[index+1]
        return my_dict


class BenchmarkSummary(Resource):

    def get(self):
        conn = sqlite3.connect('debs.db')
        cursor = conn.cursor()

        query = "SELECT * FROM predictions"
        result = cursor.execute(query)
        items = []
        for row in result:
            items.append({'scene': row[0],
                          'accuracy': row[1],
                          'prediction_speed': row[2],
                          'requested_at': row[3],
                          'submitted_at': row[4]})
        conn.close()
        return {'Submitted scenes': items,
                'total runtime': Benchmark.total_time_score}


class BenchmarkResults(Resource):
    @classmethod
    def results(cls, scenes_count):
        print("Calling Bench Results")
        conn = sqlite3.connect('debs.db')
        cursor = conn.cursor()

        query = "SELECT SUM(accuracy), SUM(precision), SUM(recall), SUM(prediction_speed) FROM predictions"
        cursor.execute(query)
        result = cursor.fetchone()
        conn.close()

        if result[0]:
            accuracy = float(result[0])/TOTAL_SCENES
            precision = float(result[1])/TOTAL_SCENES
            recall = float(result[2])/TOTAL_SCENES
        else:
            print("Client failed on first scene without results")
            accuracy = 0
            precision = 0
            recall = 0

        #TODO flag extended logging TEAMNAME:HOSTURL(post)
        logging.info('FINAL_RESULT accuracy:%s' % accuracy)
        logging.info('FINAL_RESULT precision:%s' % precision)
        logging.info('FINAL_RESULT recall:%s' % recall)
        logging.info('FINAL_RESULT runtime:%s' % result[3])
        logging.info('FINAL_RESULT: check_runtime:%s' % Benchmark.total_time_score)
        logging.info('FINAL_RESULT: scenes:%s' % scenes_count)

        data = {
                "accuracy": str(accuracy),
                "precision": str(precision),
                "recall": str(recall),
                "runtime": result[3],
                "check_runtime": Benchmark.total_time_score,
                "computed_scenes": scenes_count
        }
        with open("/logs/result.json", "w") as write_file:
            json.dump(data, write_file)
        logging.info("Saved final result as json")

        return {'average accuracy': result[0],
                'average precision': result[1],
                'average recall': result[2],
                'total runtime from db': result[3],
                'total runtime': Benchmark.total_time_score}

    def get(self):
        self.results()

#watchdog.register(BenchmarkResults.results, current_scene)
#atexit.register(BenchmarkResults.results, current_scene)
