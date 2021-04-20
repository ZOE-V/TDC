import pandas as pd
import numpy as np
import os, sys, json 
import warnings
warnings.filterwarnings("ignore")

from .utils import *
from .metadata import get_task2category, bm_metric_names, benchmark_names, bm_split_names, docking_target_info
from .evaluator import Evaluator

class BenchmarkGroup:
	def __init__(self, name, path = './data', file_format='csv', pyscreener_path = None, num_workers = None, num_cpus = None, num_max_call = 5000):
		'''
		-- PATH
			-- ADMET_Benchmark
				-- HIA_Hou
					-- train_val.csv
					-- test.csv
				-- Caco2_Wang
					-- train_val.csv
					-- test.csv
				....
		from tdc import BenchmarkGroup
		group = BenchmarkGroup(name = 'ADMET_Group', path = 'data/')
		predictions = {}

		for benchmark in group:
		   name = benchmark['name']
		   train_val, test = benchmark['train_val'], benchmark['test']
		   
		   # to obtain any number of train:valid split
		   train, valid = group.get_train_valid_split(benchmark = name, split_type = 'default', seed = 42, frac = [0.875, 0.125])

		   ## --- train your model --- ##
		   predictions[name] = y_pred

		group.evaluate(predictions)
		# {'caco2_wang': 0.234, 'hia_hou': 0.786}

		benchmark = group.get('Caco2_Wang')
		train, valid, test = benchmark['train'], benchmark['valid'], benchmark['test']
		## --- train your model --- ##
		group.evaluate(y_pred, benchmark = 'Caco2_Wang')
		# 0.234
		
		from tdc import BenchmarkGroup
		group = BenchmarkGroup(name = 'ADMET_Group', path = 'data/')
		predictions_list = []

		for seed in [1, 2, 3, 4, 5]:
		    predictions = {}
		    for benchmark in group:
		        name = benchmark['name']
		        train_val, test = benchmark['train_val'], benchmark['test']
		        train, valid = group.get_train_valid_split(benchmark = name, split_type = 'default', seed = seed)
		        ## --- train your model --- ##
		        y_pred = [1] * len(test)
		        predictions[name] = y_pred
		    predictions_list.append(predictions)

		group.evaluate_many(predictions_list)

		file_format: csv: for admet; pkl: for drugcomb; oracle: for docking score

		'''
		
		self.name = bm_group_load(name, path)
		self.path = os.path.join(path, self.name)
		self.datasets = benchmark_names[self.name]
		self.dataset_names = []
		self.file_format = file_format

		for task, datasets in self.datasets.items():
			for dataset in datasets:
				self.dataset_names.append(dataset)

		if self.name == 'docking_group':
			if pyscreener_path is not None:
				self.pyscreener_path = pyscreener_path
			else:
				raise ValueError("Please specify pyscreener_path!")
			
			if (num_workers is None) and (num_cpus is None):
				## automatic selections
				cpu_total = os.cpu_count()
				if cpu_total > 1:
					num_cpus = 2
				else:
					num_cpus = 1
				num_workers = int(cpu_total/num_cpus)

			self.num_workers = num_workers
			self.num_cpus = num_cpus
			self.num_max_call = num_max_call
			from .oracles import Oracle

	def __iter__(self):
		self.index = 0
		self.num_datasets = len(self.dataset_names)
		return self

	def __next__(self):
		if self.index < self.num_datasets:
			dataset = self.dataset_names[self.index]
			print_sys('--- ' + dataset + ' ---')

			data_path = os.path.join(self.path, dataset)
			if not os.path.exists(data_path):
				os.mkdir(data_path)
			if self.file_format == 'csv':
				train = pd.read_csv(os.path.join(data_path, 'train_val.csv'))
				test = pd.read_csv(os.path.join(data_path, 'test.csv'))
			elif self.file_format == 'pkl':
				train = pd.read_pickle(os.path.join(data_path, 'train_val.pkl'))
				test = pd.read_pickle(os.path.join(data_path, 'test.pkl'))
			elif self.file_format == 'oracle':
				target_pdb_file = os.path.join(self.path, dataset + '.pdb')
			self.index += 1

			if self.name == 'docking_group':
				from .oracles import Oracle
				oracle = Oracle(name = "Docking_Score", software="vina",
					pyscreener_path = self.pyscreener_path,
					receptors=[target_pdb_file],
					center=docking_target_info[dataset]['center'], size=docking_target_info[dataset]['size'],
					buffer=10, path=data_path, num_worker=self.num_workers, ncpu=self.num_cpus, num_max_call = self.num_max_call)
				data = pd.read_csv(os.path.join(self.path, 'zinc.tab'), sep = '\t')
				return {'oracle': oracle, 'data': data, 'name': dataset}
			else:
				return {'train_val': train, 'test': test, 'name': dataset}
		else:
			raise StopIteration
			
	def get_train_valid_split(self, seed, benchmark, split_type = 'default'):
		if self.name == 'docking_group':
			raise ValueError("Docking molecule generation does not have the concept of training/testing split! Checkout the usage in tdcommons.ai !")

		print_sys('generating training, validation splits...')
		dataset = fuzzy_search(benchmark, self.dataset_names)
		data_path = os.path.join(self.path, dataset)
		if self.file_format == 'csv':
			train_val = pd.read_csv(os.path.join(data_path, 'train_val.csv'))
		elif self.file_format == 'pkl':
			train_val = pd.read_pickle(os.path.join(data_path, 'train_val.pkl'))

		if split_type == 'default':
			split_method = bm_split_names[self.name][dataset]
		else:
			split_method = split_type

		frac = [0.875, 0.125, 0.0]
		'''
		if len(frac) == 3:
			# train:val:test split
			train_frac = frac[0]/(frac[0] + frac[1])
			valid_frac = 1 - train_frac
			frac = [train_frac, valid_frac, 0.0]
		else:
			# train:val split
			frac = [frac[0], frac[1], 0.0]
		'''
		if split_method == 'scaffold':
			out = create_scaffold_split(train_val, seed, frac = frac, entity = 'Drug')
		elif split_method == 'random':
			out = create_fold(train_val, seed, frac = frac)
		elif split_method == 'combination':
			out = create_combination_split(train_val, seed, frac=frac)
		else:
			raise NotImplementedError
		return out['train'], out['valid']

	def get(self, benchmark, num_max_call = 5000):
		dataset = fuzzy_search(benchmark, self.dataset_names)
		data_path = os.path.join(self.path, dataset)
		if self.file_format == 'csv':
			train = pd.read_csv(os.path.join(data_path, 'train_val.csv'))
			test = pd.read_csv(os.path.join(data_path, 'test.csv'))
		elif self.file_format == 'pkl':
			train = pd.read_pickle(os.path.join(data_path, 'train_val.pkl'))
			test = pd.read_pickle(os.path.join(data_path, 'test.pkl'))
		elif self.file_format == 'oracle':
			target_pdb_file = os.path.join(self.path, dataset + '.pdb')

		if self.name == 'docking_group':
			from .oracles import Oracle
			oracle = Oracle(name = "Docking_Score", software="vina",
				pyscreener_path = self.pyscreener_path,
				receptors=[target_pdb_file],
				center=docking_target_info[dataset]['center'], size=docking_target_info[dataset]['size'],
				buffer=10, path=data_path, num_worker=self.num_workers, ncpu=self.num_cpus, num_max_call = num_max_call)
			data = pd.read_csv(os.path.join(self.path, 'zinc.tab'), sep = '\t')
			return {'oracle': oracle, 'data': data, 'name': dataset}
		else:
			return {'train_val': train, 'test': test, 'name': dataset}

	def evaluate(self, pred, true = None, benchmark = None, m1_api = None, save_dict = True):

		if self.name == 'docking_group':
			results_all = {}

			for data_name, pred_ in pred.items():

				results = {}
				
				recalc = False

				if isinstance(pred_, dict):
					print_sys("The input is a dictionary, expected to have SMILES string as key and docking score as value!")
					docking_scores = pred_
					pred_ = list(pred_.keys())
				elif isinstance(pred_, list):
					recalc = True
					print_sys("The input is a list, docking score will be computed! If you already have the docking scores, please make the list as a dictionary with SMILES string as key and docking score as value")
				else:
					raise ValueError("The input prediction must be a dictionary with SMILES and their docking scores or a list of SMILES!")
				## pred is a list of smiles strings or a dictionary of smiles strings if docking scores are already calculated...
				if len(pred_) != 100:
					raise ValueError("The expected output is a list/dictionary of top 100 molecules!")
				
				if recalc:
					dataset = fuzzy_search(benchmark, self.dataset_names)

					# docking scores for the top K smiles (K <= 100)
					target_pdb_file = os.path.join(self.path, dataset + '.pdb')

					oracle = Oracle(name = "Docking_Score", software="vina",
						pyscreener_path = self.pyscreener_path,
						receptors=[target_pdb_file],
						center=docking_target_info[dataset]['center'], size=docking_target_info[dataset]['size'],
						buffer=10, path=data_path, num_worker=self.num_workers, ncpu=self.num_cpus, num_max_call = 10000)

					docking_scores = oracle(pred_)
				print_sys("---- Calculating average docking scores ----")
				if len(np.where(np.array(list(docking_scores.values()))>0)[0]) > 0.7:
					## check if the scores are all positive.. if so, make them all negative
					docking_scores = {j: -k for j, k in docking_scores.items()}
				if save_dict:
					results['docking_scores_dict'] = docking_scores
				values = np.array(list(docking_scores.values()))
				results['top100'] = np.mean(values)
				results['top10'] = np.mean(sorted(values)[:10])
				results['top1'] = min(values)

				if m1_api is None: 
					print_sys('Ignoring M1 Synthesizability Evaluations. You can still submit your results without m1 score. Although for the submission, we encourage inclusion of m1 scores. To opt-in, set the m1_api to the token obtained via: https://tdcommons.ai/functions/oracles/#moleculeone')
				else:
					print_sys("---- Calculating molecule.one synthesizability score ----")
					from .oracles import Oracle
					m1 = Oracle(name = 'Molecule One Synthesis', api_token = m1_api)
					import heapq
					from operator import itemgetter
					top10_docking_smiles = list(dict(heapq.nsmallest(10, docking_scores.items(), key=itemgetter(1))).keys())
					m1_scores = m1(top10_docking_smiles)
					scores_array = list(m1_scores.values())
					scores_array = np.array([float(i) for i in scores_array])
					scores_array[np.where(scores_array == -1.0)[0]] = 10 # m1 score errors are usually large complex molecules
					if save_dict:
						results['m1_dict'] = m1_scores
					results['m1'] = np.mean(scores_array)
					results['docking_m1'] = np.mean([docking_scores[i] for i, j in m1_scores.items()])
                    
				print_sys("---- Calculating molecular filters scores ----")
				from .chem_utils import MolFilter
				## follow guacamol
				filters = MolFilter(filters = ['PAINS', 'SureChEMBL', 'Glaxo'], property_filters_flag = False)
				pred_filter = filters(pred_)
				results['pass_list'] = pred_filter
				results['%pass'] = float(len(pred_filter))/100
				results['top1_%pass'] = max([docking_scores[i] for i in pred_filter])
				print_sys("---- Calculating diversity ----")
				from .evaluator import Evaluator
				evaluator = Evaluator(name = 'Diversity')
				score = evaluator(pred_)
				results['diversity'] = score
				print_sys("---- Calculating novelty ----")
				evaluator = Evaluator(name = 'Novelty')
				training = pd.read_csv(os.path.join(self.path, 'zinc.tab'), sep = '\t')
				score = evaluator(pred_, training.smiles.values)
				results['novelty'] = score

				results_all[data_name] = results
			return results_all

		if true is None:
			# test set evaluation
			metric_dict = bm_metric_names[self.name]
			out = {}
			for data_name, pred_ in pred.items():
				data_name = fuzzy_search(data_name, self.dataset_names)
				data_path = os.path.join(self.path, data_name)
				if self.file_format == 'csv':
					test = pd.read_csv(os.path.join(data_path, 'test.csv'))
				elif self.file_format == 'pkl':
					test = pd.read_pickle(os.path.join(data_path, 'test.pkl'))
				y = test.Y.values
				evaluator = eval('Evaluator(name = \'' + metric_dict[data_name] + '\')')
				out[data_name] = {metric_dict[data_name]: round(evaluator(y, pred_), 3)}

				# If reporting accuracy across target classes
				if 'target_class' in test.columns:
					test['pred'] = pred_
					for c in test['target_class'].unique():
						data_name_subset = data_name + '_' + c
						test_subset = test[test['target_class']==c]
						y_subset = test_subset.Y.values
						pred_subset = test_subset.pred.values

						evaluator = eval('Evaluator(name = \'' +
									     metric_dict[data_name_subset] + '\')')
						out[data_name_subset] = {metric_dict[data_name_subset]:
							        round(evaluator(y_subset, pred_subset), 3)}
			return out
		else:
			# validation set evaluation
			if benchmark is None:
				raise ValueError('Please specify the benchmark name for us to retrieve the standard metric!')
			data_name = fuzzy_search(benchmark, self.dataset_names)
			metric_dict = bm_metric_names[self.name]
			evaluator = eval('Evaluator(name = \'' + metric_dict[data_name] + '\')')
			return {metric_dict[data_name]: round(evaluator(true, pred), 3)}

	def evaluate_many(self, preds):
		"""
		:param preds: list of dict<str dataset_name: list of float>
		:return: dict<dataset_name: [mean_metric_result, std_metric_result]

		This function returns the data in a format needed to submit to the Leaderboard
		"""
		if len(preds) < 5:
			return ValueError("Must have predictions from at least five runs for leaderboard submission")
		individual_results = []
		for pred in preds:
			retval = self.evaluate(pred)
			individual_results.append(retval)

		given_dataset_names = list(individual_results[0].keys())
		aggregated_results = {}
		for dataset_name in given_dataset_names:
			my_results = []
			for individual_result in individual_results:
				my_result = list(individual_result[dataset_name].values())[0]
				my_results.append(my_result)
			u = np.mean(my_results)
			std = np.std(my_results)
			aggregated_results[dataset_name] = [round(u, 3), round(std, 3)]
		return aggregated_results
