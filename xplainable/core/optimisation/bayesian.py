import hyperopt
from hyperopt import hp, tpe, Trials
from hyperopt.early_stop import no_progress_loss
from hyperopt.fmin import fmin
from timeit import default_timer as timer
import sklearn.metrics as skm
from sklearn.model_selection import StratifiedKFold
import numpy as np
import pandas as pd
from ..ml.classification import XClassifier
import warnings
import numpy as np
import time

#suppress warnings
warnings.filterwarnings('ignore')


class XParamOptimiser:
    """ Baysian optimisation for hyperparameter tuning of xplainable models.

        Args:
            metric (str, optional): Optimisation metric. Defaults to 'f1'.
            early_stopping (int, optional): Stops early if no improvement.
            n_trials (int, optional): Number of trials to run. Defaults to 30.
            folds (int, optional): Number of folds for CV split. Defaults to 5.
            shuffle (bool, optional): Shuffle the CV splits. Defaults to False.
            subsample (float, optional): Subsamples the training data.
            alpha (float, optional): Sets the alpha of the model.
            random_state (int, optional): Random seed. Defaults to 1.
    """

    def __init__(
        self,
        metric='brier-loss',
        early_stopping=30,
        n_trials=30,
        n_folds=5,
        shuffle=False,
        subsample=1,
        alpha=0.01,
        max_depth_space = [4, 22, 2],
        min_leaf_size_space = [0.005, 0.08, 0.005],
        min_info_gain_space = [0.005, 0.08, 0.005],
        weight_space = [0, 5, 0.25],
        power_degree_space = [1, 7, 2],
        sigmoid_exponent_space = [0.5, 4, 0.25],
        verbose=True, random_state=1
        ):

        super().__init__()

        # Store class variables
        self.metric = metric
        self.early_stopping = early_stopping
        self.n_trials = n_trials
        self.n_folds = n_folds
        self.shuffle = shuffle
        self.subsample = subsample
        self.alpha = alpha
        self.verbose = verbose
        self.random_state = random_state

        self.max_depth_space = max_depth_space
        self.min_leaf_size_space = min_leaf_size_space
        self.min_info_gain_space = min_info_gain_space
        self.weight_space = weight_space
        self.power_degree_space = power_degree_space
        self.sigmoid_exponent_space = sigmoid_exponent_space

        # Callback support
        self.callback = None
        self.iteration = 1
        self.best_score = -np.inf

        # Instantiate class objects
        self.x = None
        self.y = None
        self.id_columns = []
        self.models = {i: XClassifier(
            map_calibration=False) for i in range(n_folds)}
        self.folds = {}
        self.results = []

    def _cv_fold(self, params):
        """ Runs an iteration of cross-validation for a set of parameters.

        Args:
            params (dict): The parameters to be tested in iteration.

        Returns:
            float: The average cross-validated score of the selected metric.
        """

        # Copy x and y class variables
        X_ = self.x.reset_index(drop=True)
        y_ = self.y.reset_index(drop=True)

        scores = []
        _has_nan = False
        start = time.time()
        # Run iteration over n_folds
        for i, model in self.models.items():
            
            # Instantiate and fit model
            model.update_feature_params(model.columns, **params)

            test_index = self.folds[i]['test_index']

            # Get predictions for fold
            if self.metric in ['brier-loss', 'log-loss', 'roc-auc']:
                y_prob = model.predict_score(X_.loc[test_index])
                y_prob = np.clip(y_prob, 0, 1)
                y_pred = (y_prob > 0.5).astype(int)
            else:
                y_pred = model.predict(X_.loc[test_index], remap=False)

            y_test = y_.loc[test_index]

            # Calculate the score for the fold
            if self.metric == 'macro-f1':
                scores.append(skm.f1_score(y_test, y_pred, average='macro'))

            elif self.metric == 'weighted-f1':
                scores.append(skm.f1_score(y_test, y_pred, average='weighted'))

            elif self.metric == 'positive-f1':
                scores.append(skm.f1_score(y_test, y_pred, average=None)[1])

            elif self.metric == 'negative-f1':
                scores.append(skm.f1_score(y_test, y_pred, average=None)[0])

            elif self.metric == 'macro-precision':
                scores.append(
                    skm.precision_score(y_test, y_pred, average='macro'))

            elif self.metric == 'weighted-precision':
                scores.append(
                    skm.precision_score(y_test, y_pred, average='weighted'))

            elif self.metric == 'positive-precision':
                scores.append(
                    skm.precision_score(y_test, y_pred, average=None)[1])

            elif self.metric == 'negative-precision':
                scores.append(
                    skm.precision_score(y_test, y_pred, average=None)[0])

            elif self.metric == 'macro-recall':
                scores.append(
                    skm.precision_score(y_test, y_pred, average='macro'))

            elif self.metric == 'weighted-recall':
                scores.append(
                    skm.precision_score(y_test, y_pred, average='weighted'))

            elif self.metric == 'positive-recall':
                scores.append(
                    skm.precision_score(y_test, y_pred, average=None)[1])

            elif self.metric == 'negative-recall':
                scores.append(
                    skm.precision_score(y_test, y_pred, average=None)[0])

            elif self.metric == 'accuracy':
                scores.append(skm.accuracy_score(y_test, y_pred))

            elif self.metric == 'brier-loss':
                # Negative as we want to minimise the score
                scores.append(1 - skm.brier_score_loss(y_test, y_prob))

            elif self.metric == 'log-loss':
                # Negative as we want to minimise the score
                scores.append(-skm.log_loss(y_test, y_prob))

            elif self.metric == 'roc-auc':
                try:
                    scores.append(skm.roc_auc_score(y_test, y_prob))
                except Exception as e:
                    scores.append(np.nan)
                    _has_nan = True

            else:
                scores.append(skm.f1_score(y_test, y_pred, average='weighted'))

            if self.callback:
                # fold callback
                self.callback.fold(i+1)

        score = np.nanmean(scores) if _has_nan else np.mean(scores)

        run_time = time.time() - start
        run_info = {
            'params': params,
            'score': score,
            'run_time': run_time
        }
        
        self.results.append(run_info)

        return score

    def _convert_int_params(self, names, params):
        """Converts a given set of parameters to integer values.

        Args:
            names (list): A list of params with integer values.
            params (dict): The parameter dictionary to be updated.

        Returns:
            dict: The transformed dictionary of parameters.
        """

        # Iterate through names
        for n in names:

            # Get parameter value
            val = params[n]

            # Apply conversion if the param is a number
            if isinstance(val, (int, float)):
                params[n] = int(val)

        return params

    def _objective(self, params):
        """ The objective function for hyperopt optimisation.

        Args:
            params (dict): A set of params for an optimisation iteration.

        Returns:
            dict: Meta-data for hyperopt.
        """

        # Instantiate start timer for param set
        start = timer()

        # Assert values are of int type before bayesian optimisation
        int_types = ['max_depth']
        params = self._convert_int_params(int_types, params)

        # Set the alpha
        params['alpha'] = self.alpha

        if self.callback:
            self.callback.update_params(**params)

        # Run cross validation and get score
        score = self._cv_fold(params)

        if self.callback:
            # iteration callback
            self.callback.iteration(self.iteration)
            # metric callback
            if score > self.best_score:
                self.callback.metric(abs(round(score*100, 2)))
                self.best_score = score

            if self.iteration < self.n_trials:
                self.iteration += 1

        # Calculate the run time
        run_time = timer() - start

        return {"loss": -score, "params": params, "train_time": run_time,
                "status": hyperopt.STATUS_OK}

    def _instantiate(self):

        X_ = self.x.reset_index(drop=True)
        y_ = self.y.reset_index(drop=True)

        if self.shuffle:
            folds = StratifiedKFold(
                n_splits=self.n_folds,
                shuffle=self.shuffle,
                random_state=self.random_state
                )

        else:
            folds = StratifiedKFold(n_splits=self.n_folds, shuffle=self.shuffle)

        self.folds = {i: {'train_index': train_index, 'test_index': test_index} for \
            i, (train_index, test_index) in enumerate(folds.split(X_, y_))}

        for i, v in self.folds.items():
            self.models[i].fit(
                X_.loc[v['train_index']],
                y_.loc[v['train_index']],
                id_columns=self.id_columns
                )

    def optimise(self, x, y, id_columns=[], verbose=True, callback=None):
        """ Get an optimised set of parameters for an xplainable model.

        Args:
            x (pandas.DataFrame): The x variables used for prediction.
            y (pandas.Series): The true values used for validation.
            id_columns (list, optional): ID columns in dataset. Defaults to [].
            verbose (bool, optional): Sets output amount. Defaults to True.

        Returns:
            dict: The optimised set of parameters.
        """

        # Store class variables
        self.x = x.copy()
        self.y = y.copy()
        self.id_columns = id_columns
        self._instantiate()

        self.callback = callback

        # Encode target categories if not numeric
        
        if self.y.dtype == 'object':

            # Cast as category
            target_ = self.y.astype('category')

            # Get the inverse label map
            target_map_inv = dict(enumerate(target_.cat.categories))

            # Get the label map
            target_map = {
                value: key for key, value in target_map_inv.items()}

            # Encode the labels
            self.y = self.y.map(target_map)
        

        # updates data types for cython handling
        n_cols = self.x.select_dtypes(include=np.number).columns.tolist()
        self.x[n_cols] = self.x[n_cols].astype('float64')
        self.y = self.y.astype('float64')

        # Apply subsampling
        if self.subsample < 1:
            self.x = self.x.sample(
                int(len(self.x) * self.subsample),
                random_state=self.random_state
                )

            self.y = self.y[self.x.index]

        self.x = self.x.reset_index(drop=True)
        self.y = self.y.reset_index(drop=True)

        # Instantiate the search space for hyperopt
        space = {
            'max_depth': hp.choice(
                'max_depth', np.arange(*self.max_depth_space)),
            'min_leaf_size': hp.choice(
                'min_leaf_size', np.arange(*self.min_leaf_size_space)),
            'min_info_gain': hp.choice(
                'min_info_gain', np.arange(*self.min_info_gain_space)),
            'weight': hp.choice('weight', np.arange(*self.weight_space)),
            'power_degree': hp.choice(
                'power_degree', np.arange(*self.power_degree_space)),
            'sigmoid_exponent': hp.choice(
                'sigmoid_exponent', np.arange(*self.sigmoid_exponent_space))
            }

        # Instantiate trials
        trials = Trials()

        # Run hyperopt parameter search
        fmin(fn=self._objective,
             space=space,
             algo=tpe.suggest,
             max_evals=self.n_trials,
             trials=trials,
             verbose=verbose,
             early_stop_fn=no_progress_loss(self.early_stopping),
             rstate=np.random.default_rng(self.random_state)
             )

        # Find maximum metric value across the trials
        idx = np.argmin(trials.losses())
        best_params = trials.trials[idx]["result"]["params"]

        # iteration callback completed
        if self.callback:
            self.callback.update_params(**best_params)

        # Return the best parameters
        return best_params