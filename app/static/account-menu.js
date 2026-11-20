const accountMenu=document.getElementById('account-menu');
const accountMenuTrigger=document.getElementById('account-menu-trigger');
function setAccountMenuOpen(open){accountMenu.classList.toggle('hidden',!open);accountMenuTrigger.setAttribute('aria-expanded',String(open));}
accountMenuTrigger.addEventListener('click',()=>setAccountMenuOpen(accountMenu.classList.contains('hidden')));
accountMenu.addEventListener('click',event=>{if(event.target.closest('.account-menu-item'))setAccountMenuOpen(false);});
document.addEventListener('click',event=>{if(!accountMenu.contains(event.target)&&!accountMenuTrigger.contains(event.target))setAccountMenuOpen(false);});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!accountMenu.classList.contains('hidden')){setAccountMenuOpen(false);accountMenuTrigger.focus();}});
