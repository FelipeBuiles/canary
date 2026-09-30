"""Intercept real SDK replay with synthetic secrets; no live transmission.

Run with novel_to_comic/.venv/bin/python scripts/verify_replay_privacy.py.
Requires existing web dependencies and pinned Playwright Chromium. Starts and
stops its own loopback Vite process; every API/auth/ingestion request is locally
fulfilled and other external requests are blocked. The fixture-only SDK bypasses
bot filtering and enables a local recording config to exercise the boundary;
no consent or live settings are changed. Summary goes to /tmp, without payloads.
"""
import os, subprocess, time, json, re, gzip, base64, zlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import httpx
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1];origin='http://127.0.0.1:18765'
env={k:v for k,v in os.environ.items() if not any(t in k for t in ['POSTHOG','STRIPE','SUPABASE','OPENAI','LITELLM'])}
env.update(VITE_POSTHOG_PROJECT_TOKEN='phc_local_intercept_fixture',VITE_POSTHOG_HOST='https://us.i.posthog.com',VITE_SUPABASE_URL=origin,VITE_SUPABASE_PUBLISHABLE_KEY='fixture-only',VITE_CANARY_ENV='development')
log=open('/tmp/canary-replay-vite.log','w')
server=subprocess.Popen(['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','18765','--strictPort'],cwd=root/'web',env=env,stdout=log,stderr=log)
secret='UNPUBLISHED_DISTINCTIVE_SECRET_7A63'
requests=[]; intercepted=[];capture_errors=[]
user={'id':'11111111-1111-4111-8111-111111111111','email':secret+'@example.invalid','aud':'authenticated','role':'authenticated','created_at':'2026-09-30T00:00:00Z','app_metadata':{'provider':'email'},'user_metadata':{'studio_name':secret}}
status={'id':secret,'project_name':secret,'created_at':'2026-09-30T00:00:00Z','total_cost_credits':0,'misc_cost_credits':0,'total_estimated_cost_credits':0,'is_running':False,'has_cover':False,'style_selected':True,'is_public':False,'share_token':None,'page_count':1,'active_jobs':[], 'stages':{stage:{'status':'complete','approved':True,'stale':False} for stage in ['extract','brief','style','cast','adapt','plan','draw','finish']}}
status['stages']['brief']['status']='awaiting_review'
brief={key:[secret] for key in ['story_promises','themes','ambiguities','motifs','protected_language','essential_events','character_turns','desired_emphasis']}
brief.update(revision=1,content_sha256='a'*64,status='draft',point_of_view=secret,narrator_treatment=secret,tone=secret,transformation_level='medium_specific',target_page_min=1,target_page_max=2)
story={'brief':brief,'story_bible':{'title':secret,'author':secret,'total_scenes':0,'characters':[],'locations':[],'scenes':[],'narrative_arcs':[],'style_notes':None,'props':[]}}
def decode_request(request):
    raw=request.post_data_buffer
    if not raw:return None
    if request.headers.get('content-encoding')=='gzip' or raw.startswith(b'\x1f\x8b'):raw=gzip.decompress(raw)
    try:return json.loads(raw)
    except Exception:
        try:
            fields=parse_qs(raw.decode());data=fields.get('data',[None])[0]
            if data:
                decoded=base64.b64decode(data)
                for decoder in (lambda d:d,gzip.decompress,zlib.decompress):
                    try:return json.loads(decoder(decoded))
                    except Exception:pass
        except Exception:pass
    capture_errors.append(str(raw[:80]));return None
try:
    for _ in range(100):
        if server.poll() is not None:raise RuntimeError('Vite failed: '+Path('/tmp/canary-replay-vite.log').read_text())
        try:
            if httpx.get(origin,trust_env=False).status_code==200:break
        except Exception:pass
        time.sleep(.1)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            context=browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
            def route_handler(route):
                request=route.request;url=urlparse(request.url);requests.append(request.url)
                headers={'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'}
                if url.hostname=='us.i.posthog.com':
                    if '/flags/' in url.path or '/decide/' in url.path:
                        body={'sessionRecording':{'endpoint':'/s/','sampleRate':1,'minimumDurationMilliseconds':0},'autocapture_opt_out':False}
                    else:
                        data=decode_request(request)
                        if data is not None:intercepted.append(data)
                        body={'status':1}
                    route.fulfill(status=200,headers=headers,content_type='application/json',body=json.dumps(body));return
                if url.netloc!='127.0.0.1:18765':route.abort();return
                if url.path.startswith('/auth/v1/'):
                    route.fulfill(status=200,content_type='application/json',body=json.dumps(user if url.path=='/auth/v1/user' else {'external':{'google':False}}));return
                if url.path.startswith('/api/'):
                    if url.path=='/api/events/account' or url.path=='/api/events':body={'status':'accepted'};response_status=202
                    elif url.path=='/api/projects':body=[];response_status=200
                    elif url.path.endswith('/status'):body=globals()['status'];response_status=200
                    elif url.path.endswith('/story'):body=story;response_status=200
                    elif url.path=='/api/credits/balance':body={'balance_credits':0};response_status=200
                    else:body={'detail':secret};response_status=500
                    route.fulfill(status=response_status,content_type='application/json',body=json.dumps(body));return
                route.continue_()
            context.route('**/*',route_handler)
            page=context.new_page();page.goto(origin+'/login?token='+secret)
            page.get_by_role('textbox').first.wait_for()
            # Import the same Vite-prebundled SDK module used by production initTelemetry.
            transformed=httpx.get(origin+'/src/telemetry.ts',trust_env=False).text
            matches=re.findall(r'["\']([^"\']*module[._-]+no[._-]+external[^"\']*)["\']',transformed)
            sdkpath=next(path for path in matches if path.startswith('/node_modules/'))
            page.evaluate('''async sdkpath => {
                const telemetry=await import('/src/telemetry.ts'); await telemetry.initTelemetry();
                const {default:sdk}=await import(sdkpath); window.fixtureSdk=sdk;window.fixtureEvents=[];window.fixtureRawTypes=[];
                sdk.set_config({ opt_out_useragent_filter:true, before_send:event=>{window.fixtureRawTypes.push(event.event);const clean=telemetry.scrubEvent(event);if(clean)window.fixtureEvents.push(clean);return clean;} });
                sdk.sessionRecording.onRemoteConfig({ok:true,config:{sessionRecording:{endpoint:'/s/',sampleRate:1,minimumDurationMilliseconds:0}}});
                sdk.startSessionRecording(true);sdk.capture("$pageview",{canonical_path:"/login"});
            }''',sdkpath)
            def add_private_dom(label):
                page.evaluate('''({secret,label})=>{
                  const region=document.createElement('section');region.id='fixture-private';
                  region.innerHTML=`<button data-ph-unmask title="${secret}" aria-label="${secret}" class="${secret}">${secret}</button><nav>${secret}</nav><label>${secret}</label><select><option>${secret}</option></select><textarea placeholder="${secret}" name="${secret}">${secret}</textarea><input value="${secret}" aria-label="${secret}"><img src="/private/${secret}.png"><svg><text>${secret}</text></svg><iframe src="/private/${secret}"></iframe><a href="https://${secret}.invalid/${secret}">${secret}</a><div style="background-image:url(/private/${secret})" data-secret="${secret}">${secret}</div>`;
                  document.body.append(region);document.title=secret+label;
                }''',{'secret':secret,'label':label})
                page.locator('#fixture-private button').click()
                page.locator('#fixture-private textarea').fill(secret+'_TYPED')
                page.evaluate('''secret=>{document.querySelector('#fixture-private button').textContent=secret+'_MUTATED';document.querySelector('#fixture-private button').setAttribute('aria-label',secret+'_ATTRIBUTE'); window.dispatchEvent(new ErrorEvent('error',{error:Object.assign(new Error(secret+'_ERROR'),{name:secret+'_ERROR_TYPE'}),message:secret+'_ERROR'}));}''',secret)
                page.wait_for_timeout(2500)
                page.evaluate('window.fixtureSdk.sessionRecording.flushBeforeIdentityReset()')
                page.wait_for_timeout(1500)
                page.evaluate("document.querySelector('#fixture-private').remove()")
            page.locator('input[type=email]').fill(secret+'@example.invalid')
            page.locator('input[type=password]').fill(secret+'_PASSWORD')
            add_private_dom('auth')
            payload=base64.urlsafe_b64encode(json.dumps({'sub':user['id'],'exp':int(time.time())+3600,'aud':'authenticated'}).encode()).decode().rstrip('=')
            token='eyJhbGciOiJIUzI1NiJ9.'+payload+'.Zml4dHVyZQ'
            page.evaluate("async token=>{const {supabase}=await import('/src/lib/supabase.ts');const result=await supabase.auth.setSession({access_token:token,refresh_token:'fixture-refresh'});if(result.error)throw result.error;}",token)
            # Same-document route transitions exercise URL changes with private IDs/query/hash.
            for path,label in [('/backoffice?token='+secret,'backoffice'),('/project/'+secret+'/story?prompt='+secret+'#'+secret,'editor'),('/auth/callback?code='+secret,'callback-error')]:
                page.evaluate('path=>{history.pushState({},"",path);window.dispatchEvent(new PopStateEvent("popstate"));}',path)
                page.wait_for_timeout(500)
                if label=='editor':
                    page.get_by_role('region',name='SOURCE MANUSCRIPT').wait_for()
                    page.get_by_role('button',name='Edit STORY PROMISES',exact=True).click()
                    page.locator('textarea').first.fill(secret+'_EDITOR_INPUT')
                    page.get_by_role('button',name='SAVE BRIEF',exact=True).click()
                    page.get_by_role('alert').first.wait_for()
                    assert secret in page.get_by_role('alert').first.inner_text()
                add_private_dom(label)
            page.go_back();page.wait_for_timeout(500);page.go_forward();page.wait_for_timeout(500)
            events=json.loads(page.evaluate('JSON.stringify(window.fixtureEvents)'))
            snapshots=[event for event in events if event['event']=='$snapshot']

            assert snapshots,'No serialized replay payloads observed'
            frames=[frame for event in snapshots for frame in event['properties']['$snapshot_data']]
            assert any(frame['type']==2 and isinstance(frame.get('data'),dict) and 'node' in frame['data'] for frame in frames),'No usable full snapshot survived'
            assert any(frame['type']==3 and frame.get('data',{}).get('source')==0 for frame in frames),'No mutation frames survived'
            assert secret not in json.dumps(events),'Synthetic secret leaked through before_send'
            assert intercepted,'No outgoing SDK transport captured'
            assert secret not in json.dumps(intercepted),'Synthetic secret leaked in transmitted payload'
            assert not capture_errors,'Could not decode outgoing transport: '+str(capture_errors)
            Path('/tmp/canary-replay-verification-summary.json').write_text(json.dumps({'browser':browser.version,'snapshot_events':len(snapshots),'snapshot_frames':len(frames),'transport_requests':len(intercepted),'synthetic_secret_absent':True,'routes':['login','backoffice','authenticated-project/story','auth/callback'],'all_external_requests_intercepted':True},indent=2))
            print(Path('/tmp/canary-replay-verification-summary.json').read_text(),flush=True)
        finally:browser.close()
finally:
    server.terminate()
    try:server.wait(timeout=10)
    except subprocess.TimeoutExpired:server.kill();server.wait()
    log.close();print('Own Vite/browser stopped.',flush=True)
