const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const fs=require('fs'),http=require('http'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'../dreamgoods/web');
const server=http.createServer((req,res)=>{let p=path.join(root,req.url.split('?')[0]);if(!fs.existsSync(p)||fs.statSync(p).isDirectory())p=path.join(root,'index.html');res.setHeader('Content-Type',p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(p));});
(async()=>{await new Promise(r=>server.listen(43279,'127.0.0.1',r));const browser=await chromium.launch({executablePath:process.env.CHROME_BIN || undefined,headless:true,args:['--no-sandbox']});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));let started=null,resumed=null; let uploaded=false,described=false,saved=null;
const estimate={frames:2,profiles:0,base_estimate:20,retry_estimate:10,reserve_upper:60,historical_samples:4,unit:'клиентская цена',note:'Оценка по истории модели'};
const budget={balance:200,reserved:25,available:175,admin:false,paused_jobs:0,operations:[],batches:[{id:5,title:'Генерация',unit:'клиентская цена',created:new Date().toISOString(),state:'paused',pause_reason:'Достигнут общий бюджет партии',budget:20,retry_budget:10,spent:15,reserved:5,retries:2,queued:2,running:0,paused:1,products:[{product_id:1,sku:'SHOE-001',spent:15,reserved:5,retries:2,accepted:1,cost_per_accepted:15}]}]};
const state={admin:false,account:{balance:200,billing:true,reserved:25,available:175},project:{id:1,name:'Тестовая партия',client:'Магазин'},persona:null,style_ref:null,preset:null,presets:[],settings:{plan:{},qc_enabled:true,qc_autoregen:true,qc_retries:2,aspect:'3:4',model:'test'},warnings:[],products:[],runner:{queued:0,running:0,busy:false,ok:0,fail:0,errors:0,spent:null,stopping:false},log:[],totals:{done:0,total:2,review:0,spent_all:null,avg_cost:null},metrics:null,balance:null,balance_error:''};

const preset={id:3,name:'Ручной тест',shared:false,description:'',quality:'standard',custom:{},plan:{studio:1,detail:0,worn:0,full:0,lifestyle:0},market:{key:'none',cover:false},strictness:'normal',plan_mode:'manual',manual:[{title:'Мрамор',prompt:'shoe on marble',block:'studio',count:1,model:''}],block_models:{},total:1,products:0};
const listing={presets:[preset],default_id:3,quality:[{key:'standard',name:'Стандарт',hint:'',settings:{}}],blocks:[{key:'studio',name:'Товар',max:8}],categories:[],markets:[{key:'none',name:'Без правил',aspect:'3:4',min_side:0,hint:''}],aspects:['3:4'],aspect_names:{'3:4':'Вертикально'},strictness:[{key:'normal',name:'Обычная',hint:''}],model_stats:[]};
await page.route('**/api/**',async route=>{const p=new URL(route.request().url()).pathname;let data={};
if(p==='/api/auth/me')data={id:1,org_id:1,email:'test',name:'Тест',role:'user',client:{id:1,balance:200,billing:true},consents_required:[]};
else if(p==='/api/account/storage')data={used:1024,quota:1e9};
else if(p==='/api/projects')data={projects:[state.project]};
else if(p.endsWith('/state'))data=state;
else if(p.endsWith('/trial'))data={trial:null};
else if(p.endsWith('/presets/3') && route.request().method()==='PUT'){saved=route.request().postDataJSON();Object.assign(preset,saved);data={ok:true};}
else if(p.endsWith('/presets'))data=listing;
else if(p.includes('/catalog'))data={models:[]};
else if(p.endsWith('/styles') && route.request().method()==='POST')data={id:11};
else if(p.endsWith('/styles'))data={refs:uploaded?[{id:11,name:'Мрамор',note:'',description:described?'Soft side light, overhead framing.':'',status:described?'ready':'draft',blocks:[],photos:[{id:4,asset:'test-photo'}],products:0,is_default:false,job:null}]:[],default_id:0,blocks:[]};
else if(p.endsWith('/styles/11/photos')){uploaded=true;data={ok:true};}
else if(p.endsWith('/styles/11/describe')){described=true;data={ok:true};}
else if(p.endsWith('/budgets'))data=budget;
else if(p.endsWith('/budgets/5/resume')){resumed=route.request().postDataJSON();data={ok:true};}
else if(p.endsWith('/generate/preview'))data={count:2,preset:null,estimate};
else if(p.endsWith('/generate')){started=route.request().postDataJSON();data={added:2,preset:null,batch_id:6};}
await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});

await page.goto('http://127.0.0.1:43279/studio#/presets');
await page.getByRole('button',{name:'Загрузить фото',exact:true}).waitFor();
await page.locator('.manual-reference input[type=file]').setInputFiles({name:'reference.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=','base64')});
await page.getByRole('button',{name:'Описать с ИИ · платно',exact:true}).click();
await page.getByRole('button',{name:'Использовать ИИ-описание',exact:true}).click();
await page.getByRole('textbox',{name:'Описание референса',exact:true}).fill('Soft side light, overhead framing. Warm colors.');
await page.getByRole('button',{name:'Сохранить',exact:true}).click();
await page.waitForTimeout(300);
assert(uploaded && described);assert(saved,'preset was not saved');assert.equal(saved.manual[0].reference_id,11);
assert.equal(saved.manual[0].reference_description,'Soft side light, overhead framing. Warm colors.');
await page.screenshot({path:'/tmp/dreamgoods-manual-reference.png'});
await page.getByRole('button',{name:'Убрать',exact:true}).click();
await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.waitForTimeout(300);assert.equal(saved.manual[0].reference_id,0);
assert.equal(errors.length,0,errors.join('\n'));console.log('PASS: reference upload, paid description, explicit apply, editable brief, saved manual link, removal, no JavaScript errors');
await browser.close();server.close();})().catch(e=>{console.error(e);server.close();process.exit(1)});
