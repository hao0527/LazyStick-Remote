/* Independent page: no remote-control storage, APIs or shared scripts. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id), themeKey='lazystick.huaweiAuth.theme';
  let endpoint='', key='', connected=false, busy=false, state=null;
  const fragment=new URLSearchParams(location.hash.slice(1));
  const port=Number(fragment.get('port')), suppliedKey=fragment.get('key')||'';
  // The capability is passed in a fragment, never sent to the hosting server or persisted.
  if(location.hash) history.replaceState(null,'',location.pathname+location.search);
  if(Number.isInteger(port)&&port>=1024&&port<=65535&&/^[0-9a-f]{64}$/.test(suppliedKey)){
    endpoint='http://127.0.0.1:'+port;key=suppliedKey;
  }
  function applyTheme(theme){
    const next=theme==='light'?'light':'dark';document.documentElement.dataset.theme=next;
    document.querySelector('meta[name="theme-color"]').content=next==='dark'?'#070b14':'#eef2f7';
    $('theme-toggle').textContent=next==='dark'?'☀ 切换明色':'☾ 切换暗色';
  }
  try{applyTheme(localStorage.getItem(themeKey))}catch{applyTheme('dark')}
  $('theme-toggle').addEventListener('click',()=>{
    const next=document.documentElement.dataset.theme==='dark'?'light':'dark';applyTheme(next);
    try{localStorage.setItem(themeKey,next)}catch{}
  });
  function message(text,error=false){
    $('status').textContent=text;$('status').hidden=!text;$('status').className='status'+(error?' error':'');
  }
  function render(){
    const authenticated=connected&&!!state?.authenticated, challenge=connected&&!!state?.challenge;
    $('connection-badge').textContent=connected?'已连接':'未连接';
    $('connection-badge').className='badge'+(connected?' connected':'');
    $('connection-state').textContent=connected?'助手已连接，登录信息仅在本机处理。':'首次使用，请在 Windows 电脑下载并运行助手。';
    $('helper-setup').hidden=connected;$('helper-connected').hidden=!connected;
    $('retry').hidden=!key;
    $('login-form').hidden=authenticated||challenge;
    $('login-fields').disabled=!connected||busy;
    $('challenge-panel').hidden=!challenge;$('signed-in').hidden=!authenticated;
    $('verify-form').hidden=!challenge||!state?.channel_selected;
    $('device-fields').disabled=!authenticated||busy;
    $('empty-devices').hidden=!authenticated||!!state?.devices?.length;
    for(const id of ['disconnect','retry','send-code','restart-login','logout']) $(id).disabled=busy;
    for(const el of $('verify-form').elements) el.disabled=busy;
    $('channel').disabled=busy;
    $('download').disabled=busy||!authenticated||!state?.devices?.length;
  }
  function update(next){
    state=next;
    const previousChannel=$('channel').value;
    const previous=$('device').value;
    $('device').replaceChildren();
    (state.devices||[]).forEach((d,i)=>$('device').add(new Option(d.name+(d.home?' · '+d.home:''),String(i))));
    if(!state.devices?.length) $('device').add(new Option(state.authenticated?'未找到支持的台灯':'请先登录',''));
    else if(previous!==''&&Number(previous)<state.devices.length) $('device').value=previous;
    $('channel').replaceChildren();
    (state.channels||[]).forEach(c=>{
      const kind={sms:'短信',email:'邮箱',device:'已登录设备'}[c.kind]||'验证';
      $('channel').add(new Option(kind+' · '+c.name,c.key));
    });
    if((state.channels||[]).some(c=>c.key===previousChannel))$('channel').value=previousChannel;
    render();
  }
  async function request(action,body){
    if(!endpoint||!key) throw new Error('请先运行本机助手。');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),action==='state'?8000:120000);
    try{
      const response=await fetch(endpoint+'/api/'+action,{mode:'cors',cache:'no-store',credentials:'omit',
        referrerPolicy:'no-referrer',signal:controller.signal,
        headers:{'X-LazyStick-Auth':key,...(body===undefined?{}:{'Content-Type':'application/json'})},
        ...(body===undefined?{}:{method:'POST',body:JSON.stringify(body)})});
      const data=await response.json();
      if(!response.ok){if(data.state)update(data.state);throw new Error(data.error||'操作未完成，请重试。')}
      return data;
    }catch(error){
      if(error.name==='AbortError') throw new Error('请求超时，请稍后重试。');
      if(error instanceof TypeError){connected=false;render();throw new Error('无法连接本机助手。请重新运行助手；如浏览器询问本地网络权限，请允许。')}
      throw error;
    }finally{clearTimeout(timer)}
  }
  async function operation(fn){
    if(busy)return;busy=true;render();
    try{await fn()}catch(error){message(error.message,true)}finally{busy=false;render()}
  }
  async function connect(){
    await operation(async()=>{message('正在连接本机助手…');const s=await request('state');
      if(s.version!==1)throw new Error('助手版本不匹配，请下载最新版。');connected=true;update(s);message('');});
  }
  $('retry').addEventListener('click',connect);
  $('login-form').addEventListener('submit',event=>{
    event.preventDefault();const account=$('account').value.trim(),password=$('password').value;
    operation(async()=>{message('正在登录，请稍候…');
      try{update(await request('login',{account,password}));message(state.challenge?'请选择验证方式并获取验证码。':state.devices.length?'登录成功，请选择台灯。':'未找到支持的台灯。')}
      finally{$('password').value=''}
    });
  });
  $('send-code').addEventListener('click',()=>operation(async()=>{
    message('正在获取验证码…');update(await request('channel',{key:$('channel').value}));
    message('请查看短信、邮箱或已登录设备，输入收到的验证码。');$('code').focus();
  }));
  $('verify-form').addEventListener('submit',event=>{
    event.preventDefault();operation(async()=>{message('正在验证…');
      try{update(await request('verify',{code:$('code').value.trim()}));message('登录成功，请选择台灯。')}
      finally{$('code').value=''}
    });
  });
  async function logout(){await operation(async()=>{update(await request('logout',{}));$('account').value=$('password').value=$('code').value='';message('')})}
  $('restart-login').addEventListener('click',logout);$('logout').addEventListener('click',logout);
  $('refresh-devices').addEventListener('click',()=>operation(async()=>{message('正在读取设备…');update(await request('discover',{}));message(state.devices.length?'设备已更新。':'未找到支持的台灯。')}));
  $('download').addEventListener('click',()=>operation(async()=>{
    const target=state?.devices?.[Number($('device').value)];if(!target)throw new Error('请先选择台灯。');
    message('正在生成授权文件…');const data=await request('export',{dev_id:target.dev_id,home_id:target.home_id});
    if(data.schema_version!==1||data.target?.prodId!=='2BNN'||!data.session?.service_token)throw new Error('授权文件格式不正确，请重新登录。');
    const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
    if(blob.size>8192)throw new Error('授权文件超过 8 KB，请重新登录。');
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='lamp-esp32-session.json';
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    message('授权文件已下载。请在 LazyStick 设置页导入并启用。');
  }));
  $('disconnect').addEventListener('click',()=>operation(async()=>{
    await request('stop',{});connected=false;state=null;key='';endpoint='';
    $('account').value=$('password').value=$('code').value='';update({});message('助手已退出，登录信息已清除。');
  }));
  render();if(key)connect();
})();
