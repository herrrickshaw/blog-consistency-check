
const fs=require('fs');
const html=fs.readFileSync(process.argv[1],'utf8');
const re=/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g;
let m,i=0,bad=[];
while((m=re.exec(html))){ i++;
  let c=m[1].replace(/^\s*\/\/<!\[CDATA\[/,'').replace(/\/\/\]\]>\s*$/,'');
  if(!c.trim()) continue;
  try{ new Function(c); }catch(e){ bad.push(i); }
}
console.log(JSON.stringify(bad));
