// Initialize Three.js for particle effects
function initParticles() {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
  const renderer = new THREE.WebGLRenderer({ alpha: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.getElementById('particle-bg').appendChild(renderer.domElement);

  const particles = new THREE.BufferGeometry();
  const particleCount = 1000;
  const posArray = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount * 3; i++) {
    posArray[i] = (Math.random() - 0.5) * 2000;
  }
  particles.setAttribute('position', new THREE.BufferAttribute(posArray, 3));

  const material = new THREE.PointsMaterial({
    size: 2,
    color: 0x00b7eb,
    transparent: true,
    opacity: 0.6
  });
  const particleSystem = new THREE.Points(particles, material);
  scene.add(particleSystem);

  camera.position.z = 500;

  function animate() {
    requestAnimationFrame(animate);
    particleSystem.rotation.y += 0.001;
    renderer.render(scene, camera);
  }
  animate();
}

// Debounce function
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Gamification: Mission Panel
function updateMissions(action) {
  const missions = JSON.parse(localStorage.getItem('missions') || '{}');
  missions[action] = (missions[action] || 0) + 1;
  localStorage.setItem('missions', JSON.stringify(missions));
  const missionPanel = document.getElementById('mission-panel');
  missionPanel.innerHTML = `
    <h3>Missões</h3>
    <p>Justificativas Salvas: ${missions.saveJustification || 0}</p>
    <p>Relatórios Exportados: ${missions.exportReport || 0}</p>
  `;
  if (missions[action] >= 5) {
    showBadge(action);
  }
}

function showBadge(action) {
  const badge = document.createElement('div');
  badge.className = 'badge';
  badge.innerHTML = `<span>Conquista Desbloqueada: Mestre ${action}!</span>`;
  document.body.appendChild(badge);
  setTimeout(() => badge.remove(), 3000);
}

// Page Transition
function handlePageTransition(event, url) {
  event.preventDefault();
  const container = document.querySelector('.main-wrapper');
  container.style.opacity = '0';
  container.style.transform = 'translateY(50px)';
  setTimeout(() => {
    window.location.href = url;
  }, 500);
}

document.addEventListener('DOMContentLoaded', () => {
  initParticles();
  updateMissions('pageLoad');

  // Apply transitions to all links
  document.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', (e) => handlePageTransition(e, link.href));
  });
});