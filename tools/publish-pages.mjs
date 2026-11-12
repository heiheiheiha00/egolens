// Publish only site/ to gh-pages. No model/API/private data are included.
import{execFileSync}from'node:child_process';import path from'node:path';import{fileURLToPath}from'node:url';
const cwd=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const git=args=>execFileSync('git',args,{cwd,encoding:'utf8',stdio:['pipe','pipe','pipe'],windowsHide:true}).trim();
if(git(['status','--porcelain']))throw Error('Commit the source changes before publishing');
const source=git(['rev-parse','HEAD']),tree=git(['rev-parse','HEAD:site']);
const remote=git(['ls-remote','--heads','origin','gh-pages']);let parents=[];
if(remote){git(['fetch','origin','gh-pages']);parents=['-p',git(['rev-parse','FETCH_HEAD'])]}
const commit=git(['commit-tree',tree,...parents,'-m','Publish static project page from '+source.slice(0,7)]);
console.log(git(['push','origin',commit+':refs/heads/gh-pages']));console.log('Published static tree',commit.slice(0,7));
