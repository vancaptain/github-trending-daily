import base64
import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_report
import fetch_details
import fetch_trending
import github_http

HTML = '''<article class="Box-row"><h2><a href="/owner/repo">owner / repo</a></h2>
<p>Useful &amp; small.</p><span itemprop="programmingLanguage">Rust</span>
<a href="/owner/repo/stargazers"><svg><path></path></svg>1,234</a>
<span class="float-sm-right">56 stars today</span></article>'''
STAMP = '2026-10-10T01:00:00+00:00'
SOURCE = 'https://github.com/trending?since=daily'


def ranking():
    return {'scope':'overall','period':'daily','fetched_at':STAMP,
            'sources':[{'url':SOURCE,'language':None,'fetched_at':STAMP,'sha256':'a'*64,'count':1}],
            'repos':[{'name':'owner/repo','lang':'Rust','description':'Useful project','total':1234,'today':56,
                      'observations':[{'url':SOURCE,'fetched_at':STAMP,'source_rank':1,'today':56,'total':1234}]}]}


def editorial():
    return [{'name':'owner/repo','featured':True,'cat':'model',
             'd':{'zh':'示例简介','en':'Example description'},
             'purpose':{'zh':'示例用途','en':'Example purpose'},
             'feats':{'zh':['示例功能'],'en':['Example feature']},
             'warns':{'zh':['示例限制'],'en':['Example limitation']},
             'os':['linux'],'runtime':['cli'],
             'os_evidence':[{'os':k,'url':'https://github.com/owner/repo/blob/main/README.md',
                             'note':{'zh':'官方说明','en':'Official instructions'}} for k in ('linux','cli')],
             'sources':[{'url':'https://github.com/owner/repo/blob/main/README.md',
                         'label':{'zh':'README','en':'README'}}]}]


class TrendingTests(unittest.TestCase):
    def test_parse_complete_article(self):
        row = fetch_trending.parse_trending(HTML)[0]
        self.assertEqual((row['name'],row['today'],row['total'],row['description']),('owner/repo',56,1234,'Useful & small.'))

    def test_missing_or_truncated_daily_data_fails(self):
        for html in ('<html>Blocked</html>', HTML.replace('56 stars today',''), HTML.replace('</article>','')):
            with self.assertRaises(ValueError):
                fetch_trending.parse_trending(html)

    def test_duplicate_repo_fails(self):
        with self.assertRaises(ValueError):
            fetch_trending.parse_trending(HTML+HTML)

    def test_language_union_keeps_latest_not_max_and_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch_trending,'fetch',side_effect=[
            {'data':HTML,'fetched_at':STAMP}, {'data':HTML.replace('56 stars today','40 stars today'),'fetched_at':'2026-10-10T01:01:00+00:00'}]):
            data=fetch_trending.collect(['rust'],tmp)
            self.assertEqual(data['scope'],'overall+languages')
            self.assertEqual(data['repos'][0]['today'],40)
            self.assertEqual(len(data['repos'][0]['observations']),2)
            self.assertEqual(len(list(Path(tmp).glob('*.html'))),2)
            self.assertEqual(data['sources'][0]['sha256'],github_http.hashlib.sha256(HTML.encode()).hexdigest())

    def test_fetch_failure_does_not_publish_ranking(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch_trending,'fetch',return_value={'__error__':'HTTP 502'}), redirect_stdout(io.StringIO()):
            target=str(Path(tmp)/'ranking.json')
            self.assertEqual(fetch_trending.main([target]),1)
            self.assertFalse(Path(target).exists())


class DetailsTests(unittest.TestCase):
    def test_short_lines_links_and_full_text_preserved(self):
        text='# Support\nLinux only.\nWindows unsupported.\nRequires Python 3.11+.\n[License](LICENSE)\n'+'detail '*100
        response={'data':{'encoding':'base64','content':base64.b64encode(text.encode()).decode(),'html_url':'https://github.com/owner/repo/blob/main/README.md'},'fetched_at':STAMP}
        with patch.object(fetch_details,'fetch',return_value=response), redirect_stdout(io.StringIO()):
            out,failed=fetch_details.enrich([('owner/repo',False)],excerpt_chars=30)
        self.assertEqual(failed,0)
        self.assertIn('Windows unsupported.',out['owner/repo']['readme_text'])
        self.assertTrue(out['owner/repo']['readme_truncated'])
        self.assertEqual(out['owner/repo']['readme_url'],response['data']['html_url'])

    def test_input_validation_dedup_and_release_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'repos.txt'
            path.write_text('owner/repo\nOWNER/repo *\n# comment\n')
            self.assertEqual(fetch_details.read_repos(str(path)),[('OWNER/repo',True)])
            path.write_text('owner/repo?token=secret\n')
            with self.assertRaises(ValueError): fetch_details.read_repos(str(path))

    def test_all_failed_returns_nonzero_and_records_both_resources(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch_details,'fetch',return_value={'__error__':'GitHub rate limit','status':403}), redirect_stdout(io.StringIO()):
            src=Path(tmp)/'repos.txt';dst=Path(tmp)/'out.json';src.write_text('owner/repo *\n')
            self.assertEqual(fetch_details.main([str(src),str(dst)]),1)
            out=json.loads(dst.read_text())['owner/repo']
            self.assertEqual([e['resource'] for e in out['errors']],['readme','release'])

    def test_rate_limit_stops_remaining_network_requests(self):
        failure={'__error__':'GitHub rate limit','kind':'rate_limit','status':403,'retry_after':3600}
        with patch.object(fetch_details,'fetch',return_value=failure) as request, redirect_stdout(io.StringIO()):
            out,failed=fetch_details.enrich([('owner/repo',True),('owner/other',False)])
        self.assertEqual(request.call_count,1)
        self.assertEqual(failed,3)
        self.assertTrue(out['owner/other']['errors'][0]['skipped'])

    def test_release_404_is_explicit_absence(self):
        readme={'data':{'encoding':'base64','content':base64.b64encode(b'Linux only.').decode()},'fetched_at':STAMP}
        with patch.object(fetch_details,'fetch',side_effect=[readme,{'__error__':'HTTP 404','status':404}]), redirect_stdout(io.StringIO()):
            out,failed=fetch_details.enrich([('owner/repo',True)])
        self.assertEqual(failed,0)
        self.assertEqual(out['owner/repo']['release_status'],'absent')

    def test_no_inference_from_generic_archive_or_language(self):
        self.assertIsNone(fetch_details.asset_evidence({'name':'app.tar.gz'},'v1'))
        result=fetch_details.asset_evidence({'name':'app-linux-arm64.tar.gz','browser_download_url':'https://github.com/owner/repo/releases/download/v1/app-linux-arm64.tar.gz'},'v1')
        self.assertEqual((result['os'],result['arch'],result['release_tag']),('linux','arm64','v1'))

    def test_malformed_readme_and_release_are_recorded_as_failures(self):
        readme={'data':{'encoding':'base64','content':'!!!'},'fetched_at':STAMP}
        release={'data':{'assets':[{}]},'fetched_at':STAMP}
        with patch.object(fetch_details,'fetch',side_effect=[readme,release]), redirect_stdout(io.StringIO()):
            out,failed=fetch_details.enrich([('owner/repo',True)])
        self.assertEqual(failed,2)
        self.assertEqual(len(out['owner/repo']['errors']),2)

    def test_release_assets_are_not_truncated_at_30(self):
        readme={'data':{'encoding':'base64','content':base64.b64encode(b'Readme').decode()},'fetched_at':STAMP}
        release={'data':{'tag_name':'v1','assets':[{'name':'package-%s.zip'%i} for i in range(35)]},'fetched_at':STAMP}
        with patch.object(fetch_details,'fetch',side_effect=[readme,release]), redirect_stdout(io.StringIO()):
            out,failed=fetch_details.enrich([('owner/repo',True)])
        self.assertEqual(len(out['owner/repo']['release_assets']),35)


class HttpTests(unittest.TestCase):
    def test_retry_transient_errors_then_success(self):
        response=io.BytesIO(b'{"ok":true}')
        error=urllib.error.HTTPError('https://api.github.com/example',503,'Unavailable',{},None)
        with patch.object(github_http.urllib.request,'urlopen',side_effect=[error,response]) as request, patch.object(github_http.time,'sleep') as sleep:
            result=github_http.fetch('https://api.github.com/example')
        self.assertEqual(result['data'],{'ok':True})
        self.assertEqual(request.call_count,2)
        sleep.assert_called_once_with(1)

    def test_long_rate_reset_returns_actionable_failure(self):
        headers={'X-RateLimit-Remaining':'0','X-RateLimit-Reset':str(github_http.time.time()+3600)}
        error=urllib.error.HTTPError('https://api.github.com/example',403,'Forbidden',headers,None)
        with patch.object(github_http.urllib.request,'urlopen',side_effect=error) as request, patch.object(github_http.time,'sleep') as sleep:
            result=github_http.fetch('https://api.github.com/example')
        self.assertEqual(result['kind'],'rate_limit')
        self.assertIsNotNone(result['retry_at'])
        self.assertEqual(request.call_count,1)
        sleep.assert_not_called()

    def test_secondary_limit_without_headers_does_not_retry_early(self):
        error=urllib.error.HTTPError('https://api.github.com/example',403,'Forbidden',{},io.BytesIO(b'{"message":"Secondary rate limit exceeded"}'))
        with patch.object(github_http.urllib.request,'urlopen',side_effect=error) as request, patch.object(github_http.time,'sleep') as sleep:
            result=github_http.fetch('https://api.github.com/example')
        self.assertEqual(result['kind'],'rate_limit')
        self.assertEqual(result['retry_after'],60)
        self.assertEqual(request.call_count,1)
        sleep.assert_not_called()

    def test_cache_retains_original_fetch_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(github_http.urllib.request,'urlopen',return_value=io.BytesIO(b'{"ok":true}')) as request:
            first=github_http.fetch('https://api.github.com/example',cache_dir=tmp)
            second=github_http.fetch('https://api.github.com/example',cache_dir=tmp)
        self.assertEqual(first,second)
        self.assertEqual(request.call_count,1)

    def test_credentials_not_sent_to_html(self):
        with patch.dict(github_http.os.environ,{'GH_TOKEN':'test-secret'}), patch.object(github_http.urllib.request,'urlopen',return_value=io.BytesIO(b'<html/>')) as request:
            github_http.fetch('https://github.com/trending',api=False)
        self.assertIsNone(request.call_args[0][0].get_header('Authorization'))


class ReportTests(unittest.TestCase):
    def test_unedited_ranking_does_not_invent_analysis_or_support(self):
        meta,data,more=build_report.prepare_report(ranking())
        self.assertEqual(data,[])
        self.assertEqual(more[0]['os'],[])
        self.assertEqual(meta['date'],'2026-10-10')

    def test_featured_requires_sources_bilingual_and_os_evidence(self):
        for mutate in (lambda e:e.update(sources=[]),lambda e:e.update(os_evidence=[]),lambda e:e['purpose'].pop('en')):
            edits=editorial();mutate(edits[0])
            with self.assertRaises(ValueError): build_report.prepare_report(ranking(),edits)
        meta,data,more=build_report.prepare_report(ranking(),editorial())
        self.assertEqual(len(data),1)
        self.assertEqual(data[0]['runtime'],['cli'])

    def test_invalid_counts_scope_duplicates_and_observations_rejected(self):
        cases=[]
        for value in (-1,True,'56'):
            item=ranking();item['repos'][0]['today']=value;cases.append(item)
        item=ranking();item['repos']*=2;cases.append(item)
        item=ranking();item['scope']='global';cases.append(item)
        item=ranking();item['repos'][0]['observations']=[];cases.append(item)
        item=ranking();item['repos'][0]['total']=999;cases.append(item)
        for item in cases:
            with self.assertRaises(ValueError): build_report.prepare_report(item)

    def test_unknown_editorial_repository_rejected(self):
        edits=editorial();edits[0]['name']='other/repo'
        with self.assertRaises(ValueError): build_report.prepare_report(ranking(),edits)

    def test_unsafe_evidence_urls_rejected(self):
        for url in ('javascript:alert(1)','https://user:pass@github.com/owner/repo'):
            edits=editorial();edits[0]['sources'][0]['url']=url
            with self.assertRaises(ValueError): build_report.prepare_report(ranking(),edits)

    def test_embedded_script_end_tag_escaped_and_dates_updated(self):
        source=ranking();source['repos'][0]['description']='</script><script>window.injected=true</script>'
        meta,data,more=build_report.prepare_report(source,report_date='2026-10-11')
        template=(Path(__file__).resolve().parents[1]/'references/report-template.html').read_text()
        report=build_report.render(template,meta,data,more)
        self.assertNotIn('</script><script>window.injected',report)
        self.assertIn('\\u003c/script\\u003e',report)
        self.assertIn('<title>GitHub Trending · 2026-10-11</title>',report)

    def test_snapshot_verification_detects_tampered_count_and_content(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch_trending,'fetch',return_value={'data':HTML,'fetched_at':STAMP}):
            source=fetch_trending.collect([],tmp)
            build_report.verify_snapshots(source,tmp)
            tampered=copy.deepcopy(source)
            tampered['repos'][0]['today']=900
            tampered['repos'][0]['observations'][0]['today']=900
            with self.assertRaises(ValueError): build_report.verify_snapshots(tampered,tmp)
            tampered=copy.deepcopy(source);tampered['repos']=[]
            with self.assertRaises(ValueError): build_report.verify_snapshots(tampered,tmp)
            (Path(tmp)/'overall.html').write_text(HTML+'tampered')
            with self.assertRaises(ValueError): build_report.verify_snapshots(source,tmp)

    def test_missing_template_marker_rejected(self):
        with self.assertRaises(ValueError): build_report.render('<html/>',{},[],[])


if __name__=='__main__':
    unittest.main()
