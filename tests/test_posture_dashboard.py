"""Served-JavaScript checks for the optional local posture panel (Node.js required)."""
import re
import subprocess
import unittest
from pathlib import Path

HTML = Path(__file__).parents[1] / 'aba_demo/static/index.html'


class PostureDashboardTests(unittest.TestCase):
    def run_js(self, assertions):
        html = HTML.read_text(encoding='utf-8')
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        code = "const assert = require('node:assert/strict');\n" + '\n'.join(scripts) + '\n' + assertions
        result = subprocess.run(['node', '-'], input=code, capture_output=True, text=True,
                                encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_posture_state_and_events_are_causal(self):
        self.run_js(r"""
const samples=[{time:0,identity:'confirmed',state:'standing'},
  {time:0.2,identity:'confirmed',state:'sitting'},{time:0.4,identity:'uncertain',state:null}];
assert.equal(visiblePostureSample(samples,-1),null);
assert.equal(visiblePostureSample(samples,0.1).state,'standing');
assert.equal(visiblePostureSample(samples,0.39).state,'sitting');
assert.equal(visiblePostureSample(samples,0.5).identity,'uncertain');
assert.equal(visiblePostureSample(samples,3.0),null);
const events=[{event_id:'pos-000000',kind:'stand_to_sit',start_time:0.0,end_time:0.2,
  evidence_times:[0.0,0.2],detected_time:0.6}];
assert.deepEqual(visiblePostureEvents(events,0.59),[]);
assert.equal(visiblePostureEvents(events,0.6).length,1);
assert.equal(postureStateLabel({identity:'uncertain',state:null}),'هوية الطفل غير مؤكدة');
assert.equal(postureStateLabel({identity:'confirmed',state:'sitting'}),'جالس');
assert.equal(postureStateLabel(null),'لا توجد عينة حتى هذه اللحظة');
assert.equal(POSTURE_LABELS.events.sit_to_stand,'قام من الجلوس');
assert.ok(Object.isFrozen(POSTURE_LABELS) && Object.isFrozen(POSTURE_LABELS.states));
""")

    def test_posture_bytes_are_validated_by_the_local_server(self):
        self.run_js(r"""
(async()=>{
 const calls=[];
 const fetcher=async(path,options)=>{calls.push([path,options]);
   return {ok:true,json:async()=>({status:'valid'})};};
 assert.equal(await validatePostureBytes(fetcher,'token',new Uint8Array([123,125]),10),true);
 assert.equal(calls[0][0],'/api/posture/validate');
 assert.equal(calls[0][1].headers['X-ABA-Source-Duration'],'10');
 assert.equal(calls[0][1].headers['X-ABA-Token'],'token');
 const refused=async()=>({ok:false,json:async()=>({error:'invalid_posture_document'})});
 await assert.rejects(validatePostureBytes(refused,'token',new Uint8Array([1]),10),/invalid_posture_document/);
 await assert.rejects(validatePostureBytes(fetcher,'',new Uint8Array([1]),10));
 await assert.rejects(validatePostureBytes(fetcher,'token',new Uint8Array(20*1024*1024+1),10));
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_highlight_rules_match_the_python_timeline_rules(self):
        from aba_demo.session_timeline import ACTIVITIES, level_for

        expected = {f'{activity}|{kind}': level_for(activity, 'posture', kind)
                    for activity in ACTIVITIES for kind in ('sit_to_stand', 'stand_to_sit')}
        import json
        self.run_js(r"""
const expected=%s;
for(const [key,level] of Object.entries(expected)){
  const [activity,kind]=key.split('|');
  assert.equal(postureEventLevel(activity,kind),level,key);
}
assert.equal(postureEventLevel('unknown','sit_to_stand'),'info');
assert.equal(POSTURE_LABELS.levels.flag,'علامة للمراجعة');
""" % json.dumps(expected))

    def test_panel_is_wired_as_an_optional_bound_import(self):
        html = HTML.read_text(encoding='utf-8')
        for fragment in ('id="postureFile"', 'id="posturePanel"', 'id="postureState"',
                         'id="postureEvents"', 'id="postureStatus"',
                         'validatePostureBytes(fetch,token,postureRawBytes,video.duration)',
                         'contextMatches(postureDocument,bundle,videoHash,trackingHash)',
                         'renderPostureAt(video.currentTime)',
                         'postureEventLevel(player.activityAt(event.end_time),event.kind)'):
            self.assertIn(fragment, html)


if __name__ == '__main__':
    unittest.main()
