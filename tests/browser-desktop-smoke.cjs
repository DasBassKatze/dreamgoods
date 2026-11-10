const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const fs=require('fs'),http=require('http'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'../dreamgoods/web');
const server=http.createServer((req,res)=>{let p=path.join(root,req.url.split('?')[0]);if(!fs.existsSync(p)||fs.statSync(p).isDirectory())p=path.join(root,'index.html');res.setHeader('Content-Type',p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(p));});
(async()=>{await new Promise(r=>server.listen(43279,'127.0.0.1',r));const browser=await chromium.launch({executablePath:process.env.CHROME_BIN || undefined,headless:true,args:['--no-sandbox']});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));let started=null,resumed=null;let assistantRequests=[],assistantFail=false,assistantConfigured=true;let loggedIn=false,keyCalls=0,keyValue=100,deleted=[],removed=[];
await page.clock.install();
await page.addInitScript(() => { window.dgDesktop={minimize:async()=>{},maximize:async()=>{},close:async()=>{},mode:async mode=>window.desktopMode=mode,state:async()=>({maximized:false})}; });
const imported={id:7,project_id:1,status:'upload',count:2,progress:null,error:'',photos:[{id:1,name:'one.png',asset:'one',role:'product'},{id:2,name:'two.png',asset:'two',role:'product'}],groups:[],result:{}};
const product={id:11,sku:'ART123',name:'Тест',persona_id:null,persona:null,preset_id:null,style_ref_id:null,photos:[],frames:[],done:0,total:0,profile:null,profile_job:null};
const estimate={frames:2,profiles:0,base_estimate:20,retry_estimate:10,reserve_upper:60,historical_samples:4,unit:'клиентская цена',note:'Оценка по истории модели'};
const budget={balance:200,reserved:25,available:175,admin:false,paused_jobs:0,operations:[],batches:[{id:5,title:'Генерация',unit:'клиентская цена',created:new Date().toISOString(),state:'paused',pause_reason:'Достигнут общий бюджет партии',budget:20,retry_budget:10,spent:15,reserved:5,retries:2,queued:2,running:0,paused:1,products:[{product_id:1,sku:'SHOE-001',spent:15,reserved:5,retries:2,accepted:1,cost_per_accepted:15}]}]};
const state={admin:false,account:{balance:200,billing:true,reserved:25,available:175},project:{id:1,name:'Тестовая партия',client:'Магазин'},persona:null,style_ref:null,preset:null,presets:[],settings:{plan:{},qc_enabled:true,qc_autoregen:true,qc_retries:2,aspect:'3:4',model:'test'},warnings:[],products:[],runner:{queued:0,running:0,busy:false,ok:0,fail:0,errors:0,spent:null,stopping:false},log:[],totals:{done:0,total:2,review:0,spent_all:null,avg_cost:null},metrics:null,balance:null,balance_error:''};
await page.route('**/api/**',async route=>{const p=new URL(route.request().url()).pathname;let data={};
if(p==='/api/auth/me' && !loggedIn){await route.fulfill({status:401,contentType:'application/json',body:'{}'});return;}
if(p==='/api/auth/login'){loggedIn=true;data={id:1,org_id:1,email:'admin',name:'Мастер',role:'master',client:{id:1,balance:200,billing:false},consents_required:[]};}
else if(p==='/api/auth/me')data={id:1,org_id:1,email:'test',name:'Тест',role:'master',client:{id:1,balance:200,billing:false},consents_required:[]};
else if(p==='/api/account/storage')data={used:107374182,quota:10737418240};
else if(p==='/api/projects')data={projects:[state.project]};
else if(p.endsWith('/assistant')) {
  if(route.request().method()==='GET')data={enabled:true,configured:assistantConfigured,model:'openai/gpt-4.1-mini',routes:{import:'Загрузка товаров',products:'Генерация',budgets:'Бюджеты'}};
  else {
    assistantRequests.push(route.request().postDataJSON());
    if(assistantFail){await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'Нет связи с моделью'})});return;}
    await new Promise(r=>setTimeout(r,150));
    data={answer:'Добавьте фото и проверьте группы. Одинаковый артикул объединяется в один товар.',actions:[{type:'navigate',route:'import',label:'Загрузка товаров'}],model:'openai/gpt-4.1-mini',cost_rub:.01};
  }
}
else if(p.endsWith('/state'))data={...state,admin:true,products:deleted.length?[]:[product],open_import:{id:7,status:'upload',count:imported.count}};
else if(p.endsWith('/key-status')){keyCalls++;data={value:keyValue,error:'',checking:false,checked_at:Date.now()/1000,configured:true};}
else if(p.endsWith('/products/delete')){deleted=route.request().postDataJSON().product_ids;data={deleted:deleted.length,ids:deleted};}
else if(p.endsWith('/imports/7/files') && route.request().method()==='DELETE'){
  removed=route.request().postDataJSON().paths;imported.photos=imported.photos.filter(p=>!removed.includes(p.name));imported.count=imported.photos.length;data=imported;
}
else if(p.endsWith('/imports/7'))data=imported;
else if(p.endsWith('/trial'))data={trial:null};
else if(p.endsWith('/budgets'))data=budget;
else if(p.endsWith('/budgets/5/resume')){resumed=route.request().postDataJSON();data={ok:true};}
else if(p.endsWith('/generate/preview'))data={count:2,preset:null,estimate};
else if(p.endsWith('/generate')){started=route.request().postDataJSON();data={added:2,preset:null,batch_id:6};}
await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});

await page.setViewportSize({width:520,height:620});
await page.goto('http://127.0.0.1:43279/studio');
await page.getByRole('button',{name:'Войти в студию'}).waitFor();
assert.equal(await page.locator('a[href="/"],a[href*="pricing"]').count(),0);
assert(!(await page.locator('body').innerText()).includes('Регистрация'));
await page.screenshot({path:'/tmp/dgdesktop-login.png'});
await page.getByLabel('Логин',{exact:true}).fill('admin');await page.getByLabel('Пароль',{exact:true}).fill('admin');
await page.getByRole('button',{name:'Войти в студию'}).click();
await page.setViewportSize({width:1440,height:960});
await page.getByLabel('Выбрать товар ART123',{exact:true}).waitFor();
await page.waitForFunction(()=>window.desktopMode==='workspace');
await page.waitForFunction(()=>document.querySelector('.pill-balance')?.textContent.includes('100'));
const before=keyCalls;keyValue=73;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
await page.waitForFunction(()=>document.querySelector('.pill-balance')?.textContent.includes('73'));assert(keyCalls>before);
keyValue=51; await page.clock.fastForward(31000);
await page.waitForFunction(()=>document.querySelector('.pill-balance')?.textContent.includes('51'));
await page.locator('.avatar-btn').click();
assert.equal(await page.getByRole('link',{name:'Сайт DreamGoods',exact:true}).count(),1);
assert.equal(await page.locator('a[href*="pricing"]').count(),0);
await page.locator('.avatar-btn').click();
await page.screenshot({path:'/tmp/dgdesktop-workspace.png'});
await page.locator('.card-h input[type="checkbox"]').first().check();
await page.getByRole('button',{name:'Открыть ИИ-помощника',exact:true}).click();
await page.getByLabel('Вопрос помощнику').waitFor();
await page.getByLabel('Вопрос помощнику').fill('Как загрузить фото?');
await page.getByRole('button',{name:'Отправить вопрос',exact:true}).click();
await page.getByText('Добавьте фото и проверьте группы.',{exact:false}).waitFor();
assert.equal(assistantRequests.length,1);
assert.deepEqual(assistantRequests[0].product_ids,[11]);
assert.equal(assistantRequests[0].route,'products');
const desktopBox=await page.locator('.assistant-panel').boundingBox();assert(Math.abs(desktopBox.y+desktopBox.height-(960-84))<2);
await page.screenshot({path:'/tmp/dgdesktop-assistant-conversation.png'});
await page.locator('.assistant-actions').getByRole('button',{name:'Загрузка товаров'}).click();
await page.waitForURL('**/studio#/import');
assert.equal(await page.getByLabel('Вопрос помощнику').isVisible(),true);
assistantFail=true;
await page.getByLabel('Вопрос помощнику').fill('Помоги ещё');
await page.getByRole('button',{name:'Отправить вопрос',exact:true}).click();
await page.getByRole('alert').filter({hasText:'Нет связи с моделью'}).waitFor();
assert.equal(await page.getByLabel('Вопрос помощнику').inputValue(),'Помоги ещё');
assert.equal(assistantRequests[1].history.length,2);
await page.getByRole('button',{name:'Новый диалог',exact:true}).click();
assert.equal(await page.locator('.assistant-turn').count(),0);
await page.emulateMedia({reducedMotion:'reduce'});
assert.equal(await page.locator('.assistant-panel').evaluate(e=>getComputedStyle(e).transitionDuration),'0s');
await page.setViewportSize({width:390,height:844});
const box=await page.locator('.assistant-panel').boundingBox();assert(box.x>=0 && box.x+box.width<=390);
await page.screenshot({path:'/tmp/dgdesktop-assistant-mobile.png'});
await page.setViewportSize({width:1440,height:960});
await page.screenshot({path:'/tmp/dgdesktop-assistant.png'});
await page.getByRole('button',{name:'Свернуть помощника',exact:true}).click();
assistantConfigured=false;
await page.setViewportSize({width:1024,height:720});
await page.getByRole('button',{name:'Открыть ИИ-помощника',exact:true}).click();
await page.getByRole('button',{name:'Открыть ключи Polza',exact:true}).waitFor();
assert.equal(await page.locator('.assistant-messages').evaluate(e=>e.scrollTop),0);
assert(await page.getByRole('heading',{name:'С чего начнём?',exact:true}).isVisible());
await page.screenshot({path:'/tmp/dgdesktop-assistant-small.png'});
await page.getByRole('button',{name:'Свернуть помощника',exact:true}).click();
await page.setViewportSize({width:1440,height:960});
await page.goto('http://127.0.0.1:43279/studio#/products');
await page.getByLabel('Действия товара ART123',{exact:true}).click();
await page.getByRole('button',{name:'Удалить товар ART123'}).click();
await page.getByRole('dialog').getByRole('button',{name:'Удалить',exact:true}).click();
await page.waitForTimeout(200);assert.deepEqual(deleted,[11]);
await page.goto('http://127.0.0.1:43279/studio#/import');
await page.getByRole('button',{name:'Удалить фото one.png',exact:true}).waitFor();
await page.getByRole('button',{name:'Удалить фото one.png',exact:true}).click();
await page.getByRole('dialog').getByRole('button',{name:'Удалить',exact:true}).click();
await page.waitForTimeout(200);assert.deepEqual(removed,['one.png']);
assert.equal(await page.getByRole('button',{name:'Удалить фото one.png',exact:true}).count(),0);
assert.equal(await page.getByRole('button',{name:'Удалить фото two.png',exact:true}).count(),1);
assert.equal(errors.length,0,errors.join('\n'));
console.log('PASS: compact desktop login, account-only website link, focused key refresh, assistant context/navigation/error/history reset/mobile/reduced-motion, product and uploaded photo deletion, no JS errors');
await browser.close();server.close();})().catch(e=>{console.error(e);server.close();process.exit(1)});
