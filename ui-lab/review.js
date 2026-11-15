const form=document.getElementById('launcher');
try {
  const response=await fetch('./previews.json');
  if (!response.ok) throw new Error('Preview manifest unavailable.');
  const previews=await response.json();
  const screen=document.getElementById('screen'), scenario=document.getElementById('scenario');
  previews.forEach(entry=>screen.add(new Option(entry.title,entry.id)));
  screen.value='services-appointments';
  function update() {
    const entry=previews.find(entry=>entry.id===screen.value);
    scenario.replaceChildren(...entry.states.map(state=>new Option(state,state)));
    document.getElementById('gallery').href=entry.gallery;
  }
  update(); screen.addEventListener('change',update);
  form.addEventListener('submit',event=>{
    event.preventDefault();
    const entry=previews.find(entry=>entry.id===screen.value);
    const url=new URL(entry.path,location.href);
    url.searchParams.set(entry.scenarioParam,scenario.value);
    url.searchParams.set('theme',document.getElementById('theme').value);
    location.href=url.href;
  });
} catch(error) {
  document.getElementById('launcher-status').textContent=`${error.message} Serve this directory with the documented local lab command.`;
}
