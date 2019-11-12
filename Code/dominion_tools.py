"""
Tools to read and parse Dominion ballot manifests and CVRs
"""
import json
import numpy as np
import csv
import pandas as pd
import warnings
from assertion_audit_utils import CVR


def prep_dominion_manifest(manifest, N_cards, n_cvrs):
    """
    Prepare a Dominion Excel ballot manifest (read as a pandas dataframe) for sampling.
    The manifest may have cards that do not contain the contest, but every listed CVR
    is assumed to have a corresponding card in the manifest.
    
    If the number of CVRs n_cvrs is less than the number of cards that might contain the contest,
    N_cards, an additional "phantom" batch is added to the manifest to make up the difference.
    
    Parameters:
    ----------
    manifest : dataframe
        should contain the columns
           'Tray #', 'Tabulator Number', 'Batch Number', 'Total Ballots', 'VBMCart.Cart number'
    
    Returns:
    --------
    manifest with additional column for cumulative cards and, if needed, an additional 
    batch for any phantom cards
    
    manifest_cards : the total number of cards in the manifest
    phantom_cards : the number of phantom cards required
    """
    cols = ['Tray #', 'Tabulator Number', 'Batch Number', 'Total Ballots', 'VBMCart.Cart number']
    assert set(cols).issubset(manifest.columns), "missing columns"
    manifest_cards = manifest['Total Ballots'].sum()
    if cvr_cards < N_cards:
        warnings.warn('The manifest does not account for every card cast in the contest; adding a phantom batch')
        r = {'Tray #': None, 'Tabulator Number': 'phantom', 'Batch Number': 1, \
             'Total Ballots': N_cards-cvr_cards, 'VBMCart.Cart number': None}
        manifest = manifest.append(r, ignore_index = True)
    manifest['cum_cards'] = manifest['Total Ballots'].cumsum()    
    for c in ['Tray #', 'Tabulator Number', 'Batch Number', 'VBMCart.Cart number']:
        manifest[c] = manifest[c].astype(str)
    return manifest, manifest_cards, N_cards - cvr_cards

def read_dominion_cvrs(cvr_file):
    """
    Read CVRs in Dominion format.
    Dominion uses:
       "Id" as the card ID
       "Marks" as the container for votes
       "Rank" as the rank
   
    We want to keep group 2 only (VBM)
    
    Parameters:
    -----------
    cvr_file : string
        filename for cvrs
        
    Returns:
    --------
    cvr_list : list of CVR objects
       
    """
    with open(cvr_file, 'r') as f:
        cvr_json = json.load(f)
    # Dominion export wraps the CVRs under several layers; unwrap
    # Desired output format is
    # {"ID": "A-001-01", "votes": {"mayor": {"Alice": 1, "Bob": 2, "Candy": 3, "Dan": 4}}}
    cvr_list = []
    for c in cvr_json['Sessions']:
        votes = {}
        for con in c["Original"]["Contests"]:
            contest_votes = {}
            for mark in con["Marks"]:
                contest_votes[str(mark["CandidateId"])] = mark["Rank"]
            votes[str(con["Id"])] = contest_votes
        cvr_list.append(CVR(ID = str(c["TabulatorId"])\
                                 + '_' + str(c["BatchId"]) \
                                 + '_' + str(c["RecordId"]),\
                                 votes = votes))
    return cvr_list

def sample_from_manifest(manifest, sample):
    """
    Sample from the ballot manifest
    
    Parameters:
    -----------
    manifest : dataframe
        the processed Dominion manifest
    sample : list of ints
        the cards to sample    
        
    Returns:
    -------
    sorted list of card identifiers corresponding to the sample. Card identifiers are 1-indexed
    """
    sam = np.sort(sample)
    cards = []
    lookup = np.array([0] + list(manifest['cum_cards']))
    for s in sam:
        batch_num = int(np.searchsorted(lookup, s, side='left'))
        card_in_batch = int(s-lookup[batch_num-1])
        tab = manifest.iloc[batch_num-1]['Tabulator Number']
        batch = manifest.iloc[batch_num-1]['Batch Number']
        card = list(manifest.iloc[batch_num-1][['VBMCart.Cart number','Tray #']]) \
                + [tab, batch, card_in_batch, str(tab)+'-'+str(batch)\
                + '-'+str(card_in_batch), s]
        cards.append(card)
    return cards

def sample_from_cvr(cvr_list, manifest, sample):
    """
    Sample from a list of CVRs
    
    Parameters:
    -----------
    cvr_list : list of CVR objects. This function assumes that the id for the cvr is composed
        of a scanner number, batch number, and ballot number, joined with underscores
    manifest : a ballot manifest as a pandas dataframe
    sample : list of ints
        the CVRs to sample    
        
    Returns:
    -------
    cards: sorted list of card identifiers corresponding to the sample.
    """
    sam = np.sort(sample-1) # adjust for 1-based index to 0-based index
    cards = []
    for s in sam:
        cvr_id = cvr_list[s].id
        tab, batch, card_num = cvr_id.split("_")
        if "phantom" not in cvr_id:
            manifest_row = manifest[(manifest['Tabulator Number'] == tab) \
                                    & (manifest['Batch Number'] == batch)]
            card = list(manifest_row['VBMCart.Cart number','Tray #']) \
                    + [tab, batch, card_num, str(tab)+'-'+str(batch)\
                    + '-'+str(card_num), s]
        else:
            card = ["","", tab, batch, card_num, str(tab)+'-'+str(batch) + '-'+str(card_num), s]
        cards.append(card)
    # sort by id
    cards.sort(key = lambda x: x[5])
    return cards


def write_cards_sampled(sample_file, cards, print_phantoms=True):
    """
    Write the identifiers of the sampled cards to a file.
    
    Parameters:
    ----------
    
    sample_file : string
        filename for output
        
    cards : list of lists
        'VBMCart.Cart number','Tray #','Tabulator Number','Batch Number', 'ballot_in_batch', 
              'imprint', 'absolute_card_index'
    
    print_phantoms : Boolean
        if print_phantoms, prints all sampled cards, including "phantom" cards that were not in
        the original manifest.
        if not print_phantoms, suppresses "phantom" cards
    
    Returns:
    --------
    
    """    
    with open(sample_file, 'a') as f:
        writer = csv.writer(f)
        writer.writerow(["cart", "tray", "tabulator", "batch",\
                         "card in batch", "imprint", "absolute card index"])
        if print_phantoms:
            for row in cards:
                writer.writerow(row) 
        else:
            for row in cards:
                if row[2] != "phantom":
                    writer.writerow(row) 

def test_sample_from_manifest():
    """
    Test the card lookup function
    """
    sample = [1, 99, 100, 101, 121, 200, 201]
    d = [{'Tray #': 1, 'Tabulator Number': 17, 'Batch Number': 1, 'Total Ballots': 100, 'VBMCart.Cart number': 1},\
        {'Tray #': 2, 'Tabulator Number': 18, 'Batch Number': 2, 'Total Ballots': 100, 'VBMCart.Cart number': 2},\
        {'Tray #': 3, 'Tabulator Number': 19, 'Batch Number': 3, 'Total Ballots': 100, 'VBMCart.Cart number': 3}]
    manifest = pd.DataFrame.from_dict(d)
    manifest['cum_cards'] = manifest['Total Ballots'].cumsum()
    cards = sample_from_manifest(manifest, sample)
    # cart, tray, tabulator, batch, card in batch, imprint, absolute index
    assert cards[0] == [1, 1, 17, 1, 1, "17-1-1",1]
    assert cards[1] == [1, 1, 17, 1, 99, "17-1-99",99]
    assert cards[2] == [1, 1, 17, 1, 100, "17-1-100",100]
    assert cards[3] == [2, 2, 18, 2, 1, "18-2-1",101]
    assert cards[4] == [2, 2, 18, 2, 21, "18-2-21",121]
    assert cards[5] == [2, 2, 18, 2, 100, "18-2-100",200]
    assert cards[6] == [3, 3, 19, 3, 1, "19-3-1",201]  

if __name__ == "__main__":
    test_sample_from_manifest()
