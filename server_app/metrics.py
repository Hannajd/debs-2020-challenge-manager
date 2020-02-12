from functools import reduce
import sqlite3
import json

def accuracy(a, b):
    common_keys = set(a).intersection(b)
    all_keys = set(a).union(b)
    score = len(common_keys) / len(all_keys) #key score
    if (score == 0):
        return score
    else: #value score
        pred = {}
        for k in common_keys:
            pred[k] = b[k]
        #true_values_sum = reduce(lambda x,y:int(x)+int(y),a.values())
        all_keys = dict.fromkeys(all_keys, 0)
        for k in a.keys():
            all_keys.update({k:a[k]})
        for k in b.keys():
            all_keys.update({k:b[k]})
        true_values_sum = reduce(lambda x,y:int(x)+int(y),all_keys.values())
        pred_values_sum = reduce(lambda x,y:int(x)+int(y),pred.values())
        val_score = int(pred_values_sum)/int(true_values_sum)
        if score >= val_score:
            return (score+val_score)/2
        else:
            return score


def precision(a,b):
    #return len(set(a).intersection(b))/len(a)
    common_keys = set(a).intersection(b)
    score = len(common_keys) / len(a)
    if (score == 0):
        return score
    else:
        pred = {}
        for k in common_keys:
            pred[k] = b[k]
        true_values_sum = reduce(lambda x,y:int(x)+int(y),a.values())
        pred_values_sum = reduce(lambda x,y:int(x)+int(y),pred.values())
        val_score = int(pred_values_sum)/int(true_values_sum)
        if score >= val_score:
            return (score+val_score)/2
        else:
            return score

def recall(a,b):
    common_keys = set(a).intersection(b)
    score = len(common_keys)/len(b)
    if (score == 0):
        return score
    else:
        pred = {}
        for k in common_keys:
            pred[k] = b[k]
        true_values_sum = reduce(lambda x,y:int(x)+int(y),b.values())
        pred_values_sum = reduce(lambda x,y:int(x)+int(y),pred.values())
        val_score = int(pred_values_sum)/int(true_values_sum)
        if score >= val_score:
            return (score+val_score)/2
        else:
            return score


def results(scenes_count, TOTAL_SCENES, total_time_score):
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
    # logging.info('FINAL_RESULT accuracy:%s' % accuracy)
    # logging.info('FINAL_RESULT precision:%s' % precision)
    # logging.info('FINAL_RESULT recall:%s' % recall)
    # logging.info('FINAL_RESULT runtime:%s' % result[3])
    # logging.info('FINAL_RESULT: check_runtime:%s' % Benchmark.total_time_score)
    # logging.info('FINAL_RESULT: check_runtime:%s' % scenes_count)

    data = {
            "accuracy": str(accuracy),
            "precision": str(precision),
            "recall": str(recall),
            "runtime": result[3],
            "check_runtime": total_time_score,
            "computed_scenes": scenes_count
    }
    with open("/logs/result.json", "w") as write_file:
        json.dump(data, write_file)

    return {'average accuracy': result[0],
            'average precision': result[1],
            'average recall': result[2],
            'total runtime from db': result[3],
            'total runtime': total_time_score}

# c = {'Pedestrian': '2',
#  'BigSassafras': '1',
#  'Bench': '1'}
# d  = {'Pedestrian': '2',
#  'BigSassafras': '1',
#  'Bench': '1'}
#
# print(accuracy(c,d))
# print(precision(c,d))
# print(recall(c,d))
