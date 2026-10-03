"""Served-JavaScript checks for the unified session strip (Node.js required)."""
import json
import re
import subprocess
import unittest
from pathlib import Path

HTML = Path(__file__).parents[1] / 'aba_demo/static/index.html'


class SessionStripDashboardTests(unittest.TestCase):
    def run_js(self, assertions):
        html = HTML.read_text(encoding='utf-8')
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        code = "const assert = require('node:assert/strict');\n" + '\n'.join(scripts) + '\n' + assertions
        result = subprocess.run(['node', '-'], input=code, capture_output=True, text=True,
                                encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_flag_rules_and_labels_match_the_python_timeline(self):
        from aba_demo.channel_events import CHANNELS
        from aba_demo.session_timeline import ACTIVITIES, FLAG_RULES, level_for

        expected = {f'{activity}|{channel}|{kind}': level_for(activity, channel, kind)
                    for activity in ACTIVITIES for channel, (kinds, *_) in CHANNELS.items()
                    for kind in kinds}
        rules = sorted('|'.join(rule) for rule in FLAG_RULES)
        self.run_js(r"""
const expected=%s;
for(const [key,level] of Object.entries(expected)){
  const [activity,channel,kind]=key.split('|');
  assert.equal(channelEventLevel(activity,channel,kind),level,key);
  assert.ok(CHANNEL_LABELS.kinds[kind],kind);
  assert.ok(CHANNEL_LABELS.channels[channel],channel);
}
assert.deepEqual([...CHANNEL_FLAG_RULES].sort(),%s);
assert.equal(channelEventLevel('table','posture','unknown'),'info');
assert.ok(Object.isFrozen(CHANNEL_LABELS)&&Object.isFrozen(CHANNEL_LABELS.kinds));
""" % (json.dumps(expected), json.dumps(rules)))

    def test_strip_entries_are_causal_merged_and_bound(self):
        self.run_js(r"""
const ev=(id,channel,kind,start,end,detected)=>({event_id:id,channel,kind,origin:'measured',
  start_time:start,end_time:end,detected_time:detected,evidence_times:[start,end],
  clinician_confirmation:'pending'});
const readings={
  posture:{channel:'posture',source_sha256:'v',tracking_candidate_sha256:'t',
    events:[ev('pos-1','posture','sit_to_stand',10,10.4,11)]},
  movement:{channel:'movement',source_sha256:'v',tracking_candidate_sha256:'t',
    events:[ev('lmv-1','movement','large_movement',4,7,9),ev('lmv-2','movement','large_movement',20,22,25)]},
  orientation:{channel:'orientation',source_sha256:'other',tracking_candidate_sha256:'t',
    events:[ev('ori-1','orientation','turned_away_from_task',1,2,3)]}};
const bundle={source:{sha256:'v'}};
const activityAt=t=>t<10?'movement':'table';
assert.deepEqual(visibleStripEntries(readings,bundle,'v','t',activityAt,8.9),[]);
const at12=visibleStripEntries(readings,bundle,'v','t',activityAt,12);
assert.deepEqual(at12.map(e=>[e.entry_id,e.activity,e.level]),
  [['tl-movement-lmv-1','movement','info'],['tl-posture-pos-1','table','flag']]);
assert.equal(visibleStripEntries(readings,bundle,'v','t',activityAt,30).length,3);
assert.deepEqual(visibleStripEntries(readings,null,'v','t',activityAt,30),[]);
assert.deepEqual(visibleStripEntries(readings,bundle,'v','x',activityAt,30),[]);
assert.equal(stripPosition(25,100),25);
assert.equal(stripPosition(150,100),100);
assert.equal(stripPosition(5,0),0);
assert.equal(contextDetailsLabel({}),'');
assert.equal(contextDetailsLabel({child_separable:'yes',child_location:'on_floor',
  child_handling_material:'no'}),'على الأرض · لا يمسك أداة');
assert.equal(CHANNEL_LABELS.details.adult_hand_contact,undefined);
assert.equal(contextDetailsLabel({child_separable:'no',child_location:'not_observable',
  child_handling_material:'not_observable'}),
  'تعذّر فصل جسم الطفل عن البالغ');
assert.equal(CHANNEL_LABELS.origins.suggested,'مقترح من نموذج');
assert.equal(contextDetailsLabel({child_separable:'yes',child_location:'walking'}),'يتنقّل');
""")

    def test_strip_groups_match_the_python_grouping(self):
        from aba_demo.grouping import GROUP_GAP_SECONDS, group_by_time

        entries = [{'entry_id': f'tl-x-{n}', 'start_time': start, 'end_time': end,
                    'level': level}
                   for n, (start, end, level) in enumerate(
                       [(148.2, 148.6, 'flag'), (148.0, 151.4, 'info'), (31.4, 31.6, 'info'),
                        (31.4, 31.6, 'info'), (152.3, 152.7, 'info'), (154.0, 154.2, 'info')])]
        expected = [[e['entry_id'] for e in group]
                    for group in group_by_time(entries, key='entry_id')]
        self.run_js(r"""
const entries=%s;
const groups=groupStripEntries(entries);
assert.equal(STRIP_GROUP_GAP_SECONDS,%s);
assert.deepEqual(groups.map(g=>g.entries.map(e=>e.entry_id)),%s);
assert.deepEqual(groups.map(g=>g.level),['info','flag','info']);
assert.deepEqual(groups.map(g=>[g.start_time,g.end_time]),[[31.4,31.6],[148,152.7],[154,154.2]]);
assert.deepEqual(groupStripEntries([]),[]);
""" % (json.dumps(entries), GROUP_GAP_SECONDS, json.dumps(expected)))

    def test_channel_bytes_are_validated_by_the_local_server(self):
        self.run_js(r"""
(async()=>{
 const calls=[];
 const reading={status:'valid',channel:'posture',source_sha256:'v',tracking_candidate_sha256:'t',events:[]};
 const fetcher=async(path,options)=>{calls.push([path,options]);return {ok:true,json:async()=>reading};};
 assert.deepEqual(await validateChannelBytes(fetcher,'token',new Uint8Array([123,125]),10),reading);
 assert.equal(calls[0][0],'/api/channel/validate');
 assert.equal(calls[0][1].headers['X-ABA-Source-Duration'],'10');
 const refused=async()=>({ok:false,json:async()=>({error:'unknown_channel'})});
 await assert.rejects(validateChannelBytes(refused,'token',new Uint8Array([1]),10),/unknown_channel/);
 await assert.rejects(validateChannelBytes(fetcher,'',new Uint8Array([1]),10));
 await assert.rejects(validateChannelBytes(fetcher,'token',new Uint8Array(20*1024*1024+1),10));
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_strip_is_wired_into_the_page(self):
        html = HTML.read_text(encoding='utf-8')
        for fragment in ('id="channelFiles"', 'multiple', 'id="stripPanel"', 'id="sessionStrip"',
                         'id="stripEntries"', 'id="stripStatus"',
                         'validateChannelBytes(fetch,token,rawBytes,video.duration)',
                         'visibleStripEntries(channelReadings,bundle,videoHash,trackingHash,',
                         'renderStripAt(video.currentTime)'):
            self.assertIn(fragment, html)


if __name__ == '__main__':
    unittest.main()
