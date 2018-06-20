# CIL Text Classification Project

Problem: Given a tweet from which a smiley (`:)` or `:(`) has been removed

Goal: Determine whether it used to contain a positive or a negative smiley 

## Setup

The following two steps will prepare your environment to begin training and evaluating models.

### Downloading necessary datasets

Simply run

```
cd data
bash get_dataset.bash
```

### Installing dependencies

Run (with `sudo` appended if necessary),
```
python3 setup.py install
```

Note that this can be done within a [virtual environment](https://docs.python.org/3/tutorial/venv.html). In this case, the sequence of commands would be similar to:
```
mkvirtualenv -p $(which python3) myenv
python3 setup.py install
```

when using [virtualenvwrapper](https://virtualenvwrapper.readthedocs.io/en/latest/).


## Framework Structure
* `data/` - source data files required for training/testing/validating.
* `outputs/` - output files generated by the framework, all files within are ignored in GitHub commits.
    * `models/` - any output for a model will be placed into a subdirectory here, including logs, summaries, checkpoints, and Kaggle submission `kaggle_*.csv` files, 
    * `datasources/` - any intermediate files generated by the preprocessing of a data source, which can reduce the preprocessing time for subsequent runs.
* `src/` - all source code.
    * `core/` - base classes,
    * `datasources/` - routines for reading and preprocessing entries for training and testing,
    * `models/` - machine learning model definitions,
    * `util/` - utility methods,
    * `main.py` - the training script.

Please refer to  `README.md` under these folders for detailed descriptions.

## Training the model

Simply `cd` into the `src/` directory and run
```
python3 main.py [model]
```
Our current best performing model is a Naive Bayes model, so to get the best result please run
```
python3 main.py NaiveBayes
```

## Evaluation
When the model has completed training, it will automatically perform a full evaluation on the test set and generate a submission file.

The output submission files can be found in the folder `outputs/models/[model]/` as `kaggle_<timestamp>.csv`.