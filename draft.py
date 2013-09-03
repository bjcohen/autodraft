import pandas as pd

import urllib2
import httplib
import cjson
import operator
import time 

with open('config.json') as config_fh:
    config = cjson.decode(config_fh.read())

key = config['key']
url_base = config['url_base']
api_base = config['api_base']
my_id = config['my_team_id']

endpoints = {
    ## draft-dependent
    'info' : '/draft',
    'picks' : '/picks',
    'make_pick' : '/pick_player/{pid}',
    'player_status' : '/player/{pid}/status',
    
    ## static
    'player_by_id' : '/player/{pid}',
    'player_search' : '/search/name/{name}/pos/{position}',
    'team_by_id' : '/team/{team}', ## can be team name or id
    'all_teams' : '/nfl/teams',
    'nfl_team_players' : '/nfl/team/{team}/players',
    'team_players' : '/team/{team}',
    'position_players' : '/nfl/position/{position}',
    'nfl_conferences' : '/nfl/conferences',
    'nfl_divisions' : '/nfl/divisions',
    'colleges' : '/colleges',
    'players_by_college' : '/college/{college}/players',
}

positions = ['WR', 'DST', 'TE', 'QB', 'RB', 'K']

opener = urllib2.build_opener()

def make_api_call(call, **kwargs):
    url = url_base + api_base + endpoints[call].format(**kwargs) + '?key=' + key
    res = cjson.decode(opener.open(url).read())
    return res

info = make_api_call('info')

with open('nf_data.json') as nf_fh:
    nf_data = cjson.decode(nf_fh.read())

projections = pd.DataFrame(nf_data['players']['projections'])
def nf_id_to_gnm(player_id):
    name = nf_data['players']['players'][player_id]['name']
    fname, lname = map(str.lower, name.split())
    position = nf_data['players']['players'][player_id]['position']
    query = make_api_call('player_search', name=lname, position=position)
    for r in query['results']:
        if r['first_name'].lower() == fname and
            r['last_name'].lower() == lname and
            r['fantasy_positon'].lower() == position:
            return r['id']
    return None
projections['pid'] = projections['player_id'].map(nf_id_to_gnm)
projections['position'] = projections['player_id']. \
  map(lambda player_id: nf_data['players']['players'][player_id]['position'])
projections.loc[projections['position']=='D','position'] = 'DST'
projections['risk_value'] = projections['player_id']. \
  map(lambda player_id: nf_data['risks'][player_id]['risk_value'] if
      player_id in nf_data['risks'] else None)

projections['available'] = True
mean_by_position = projections.groupby('position')['fp'].agg('mean')

projections.set_index('pid', inplace=True)

roster_slots = info['roster']['description'].split(',')

def get_best_pick(roster_slots, projections, mean_by_position):
    roster_slots = set(roster_slots)
    if 'BN' in roster_slots:
        sel = slice(None)
    else:
        sel = roster_slots

    top_per_pos = projections.loc[projections['available']] \
      .groupby('position').agg('first')[['fp','pid']]
    pos_to_pick = (top_per_pos['fp'] - mean_by_position).loc[sel].idxmax()

    return pos_to_pick, top_per_pos.loc[pos_to_pick,'pid']

all_picks = make_api_call('picks')
my_picks = filter(lambda x: x['team']['id'] == my_id, all_picks['picks'])
my_pick_times = map(lambda x: x['starts']['utc'], my_picks)

def wait_until(utctime):
    now = time.time()
    time.sleep(utctime-now)

for pick_time in my_pick_times:
    wait_until(pick_time)
    
    all_picks = make_api_call('picks')
    ## TODO: when we know what the format of this is, use this to mark
    ## players as taken instead of checking one by one (as in following loop)
    for s in all_picks['selections']:
        pass
    
    found = False
    while not found:
        pos, pid = get_best_pick(roster_slots, projections, mean_by_position)
        if make_api_call('player_status', pid=pid)['fantasy_team']:
            projections.loc[pid,'available'] = False
        else:
            found = True

    pick_result = make_api_call('make_pick', pid=pid)
    if not pick_result['success']:
        raise RuntimeError('pick failed')
            
    if pos in roster_slots:
        roster_slots.remove(pos)
    else:
        roster_slots.remove('BN')
    
