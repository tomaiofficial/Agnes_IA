/**
 * Agnes IA - Frontend Application
 * Gestion de l'affichage des pourcentages et du pipeline
 */

// Configuration WebSocket
const socketUrl = window.location.hostname === 'localhost' 
    ? 'ws://localhost:8000/ws' 
    : 'wss://' + window.location.host + '/ws';
const socket = new WebSocket(socketUrl);

// État global
let currentJobs = {};
const pipelineSteps = [
    'prompt', 'analyse', 'optimisation', 'generation', 
    'upscaling', 'face_enhancement', 'audio', 'compression', 'delivery'
];

// Poids des étapes pour le calcul des % (doit correspondre au backend)
const stepWeights = {
    'prompt': 5,
    'analyse': 5,
    'optimisation': 5,
    'generation': 25,
    'upscaling': 15,
    'face_enhancement': 15,
    'audio': 10,
    'compression': 10,
    'delivery': 15
};
const totalWeight = Object.values(stepWeights).reduce((a, b) => a + b, 0);

// Connexion WebSocket
socket.onopen = function(e) {
    console.log("✅ WebSocket connected");
    // S'abonner aux mises à jour
    socket.send(JSON.stringify({type: "subscribe", user_id: window.USER_ID || "anonymous"}));
};

socket.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    if (data.type === "job_update") {
        updateJobStatus(data.job);
    } else if (data.type === "job_completed") {
        completeJob(data.job);
    } else if (data.type === "error") {
        showError(data.message);
    } else if (data.type === "stats") {
        updateStats(data.stats);
    }
};

socket.onclose = function(event) {
    console.log("⚠️  WebSocket disconnected, reconnecting...");
    setTimeout(() => {
        window.location.reload();
    }, 5000);
};

// Mettre à jour le statut d'un job
function updateJobStatus(job) {
    currentJobs[job.job_id] = job;
    
    let jobElement = document.getElementById('job-' + job.job_id);
    if (!jobElement) {
        jobElement = createJobElement(job);
        document.getElementById('jobs-container').prepend(jobElement);
    }
    
    // Mettre à jour la barre de progression avec le % du backend
    const progress = job.progress_percent || calculateProgress(job);
    const progressBar = jobElement.querySelector('.progress-bar');
    if (progressBar) {
        progressBar.style.width = progress + '%';
        progressBar.textContent = Math.round(progress) + '%';
        
        // Changer la couleur selon la progression
        if (progress >= 100) {
            progressBar.style.backgroundColor = '#28a745'; // Vert
        } else if (progress >= 75) {
            progressBar.style.backgroundColor = '#20c997'; // Vert clair
        } else if (progress >= 50) {
            progressBar.style.backgroundColor = '#17a2b8'; // Cyan
        } else if (progress >= 25) {
            progressBar.style.backgroundColor = '#ffc107'; // Jaune
        } else {
            progressBar.style.backgroundColor = '#fd7e14'; // Orange
        }
    }
    
    // Mettre à jour le temps restant
    const timeRemaining = jobElement.querySelector('.time-remaining');
    if (timeRemaining) {
        timeRemaining.textContent = estimateTimeRemaining(job);
    }
    
    // Mettre à jour l'étape actuelle
    const currentStepEl = jobElement.querySelector('.current-step');
    if (currentStepEl && job.current_step) {
        const stepName = formatStepName(job.current_step);
        currentStepEl.textContent = 'Étape: ' + stepName;
    }
    
    // Mettre à jour les étapes
    const stepsContainer = jobElement.querySelector('.steps');
    if (stepsContainer) {
        updateStepsDisplay(stepsContainer, job);
    }
}

// Calculer la progression (fallback si le backend ne fournit pas de %)
function calculateProgress(job) {
    const completedSteps = Object.keys(job.steps || {}).filter(step => job.steps[step].success);
    let completedWeight = 0;
    
    for (const step of completedSteps) {
        completedWeight += stepWeights[step] || 0;
    }
    
    // Si on est en train de traiter une étape, ajouter une partie de son poids
    if (job.current_step && !completedSteps.includes(job.current_step)) {
        completedWeight += (stepWeights[job.current_step] || 0) * 0.5;
    }
    
    const progress = (completedWeight / totalWeight) * 100;
    return Math.round(Math.min(100, Math.max(0, progress)));
}

// Estimer le temps restant
function estimateTimeRemaining(job) {
    if (!job.start_time) return "Calcul en cours...";
    
    const elapsed = (Date.now() / 1000) - job.start_time;
    const progress = calculateProgress(job) / 100;
    
    if (progress === 0) return "Démarrage...";
    if (progress >= 1) return "Presque terminé...";
    
    const estimatedTotal = elapsed / progress;
    const remaining = estimatedTotal - elapsed;
    
    return formatDuration(remaining);
}

// Formater la durée
function formatDuration(seconds) {
    if (seconds < 60) {
        return Math.round(seconds) + 's';
    } else if (seconds < 3600) {
        return Math.round(seconds / 60) + 'm';
    } else {
        return Math.round(seconds / 3600) + 'h';
    }
}

// Formater le nom d'une étape
function formatStepName(step) {
    if (!step) return 'Inconnu';
    const names = {
        'prompt': 'Prompt',
        'analyse': 'Analyse',
        'optimisation': 'Optimisation',
        'generation': 'Génération',
        'upscaling': 'Upscaling',
        'face_enhancement': 'Visage/Mouvement',
        'audio': 'Audio',
        'compression': 'Compression',
        'delivery': 'Livraison'
    };
    return names[step] || step;
}

// Mettre à jour l'affichage des étapes
function updateStepsDisplay(container, job) {
    container.innerHTML = '';
    
    pipelineSteps.forEach(step => {
        const stepElement = document.createElement('div');
        stepElement.className = 'step';
        
        const stepName = formatStepName(step);
        const stepData = job.steps ? job.steps[step] : null;
        
        if (stepData && stepData.success) {
            stepElement.classList.add('completed');
            const stepTime = stepData.duration || 0;
            stepElement.innerHTML = '<span class="step-name">' + stepName + '</span><span class="step-time">(' + formatDuration(stepTime) + ')</span>';
        } else if (job.current_step === step) {
            stepElement.classList.add('current');
            stepElement.innerHTML = '<span class="step-name">' + stepName + '</span><span class="step-status">En cours...</span>';
        } else if (stepData && !stepData.success) {
            stepElement.classList.add('failed');
            stepElement.innerHTML = '<span class="step-name">' + stepName + '</span><span class="step-error">Erreur</span>';
        } else {
            stepElement.innerHTML = '<span class="step-name">' + stepName + '</span>';
        }
        
        container.appendChild(stepElement);
    });
}

// Créer un élément de job
function createJobElement(job) {
    const jobElement = document.createElement('div');
    jobElement.id = 'job-' + job.job_id;
    jobElement.className = 'job-card';
    
    const progress = job.progress_percent || calculateProgress(job);
    
    jobElement.innerHTML = '
        <div class="job-header">
            <span class="job-id">#' + (job.job_id.substring(0, 8)) + '</span>
            <span class="job-status">' + (job.status || 'Processing') + '</span>
        </div>
        <div class="job-info">
            <div class="current-step">Étape: ' + formatStepName(job.current_step) + '</div>
            <div class="progress-container">
                <div class="progress-bar" style="width: ' + progress + '%">' + Math.round(progress) + '%</div>
            </div>
        </div>
        <div class="job-details">
            <span class="time-remaining">Temps restant: ' + estimateTimeRemaining(job) + '</span>
            <div class="steps"></div>
        </div>
    ';
    
    return jobElement;
}

// Terminer un job
function completeJob(job) {
    const jobElement = document.getElementById('job-' + job.job_id);
    if (jobElement) {
        if (job.success) {
            jobElement.classList.add('completed');
            jobElement.querySelector('.job-status').textContent = 'Terminé';
            jobElement.querySelector('.progress-bar').style.width = '100%';
            jobElement.querySelector('.progress-bar').textContent = '100%';
            jobElement.querySelector('.progress-bar').style.backgroundColor = '#28a745';
            jobElement.querySelector('.time-remaining').textContent = 'Terminé !';
        } else {
            jobElement.classList.add('failed');
            jobElement.querySelector('.job-status').textContent = 'Échec';
            jobElement.querySelector('.time-remaining').textContent = 'Erreur: ' + (job.error || 'Inconnu');
            jobElement.querySelector('.progress-bar').style.backgroundColor = '#dc3545';
        }
    }
    delete currentJobs[job.job_id];
}

// Afficher une erreur
function showError(message) {
    const errorElement = document.createElement('div');
    errorElement.className = 'error-notification';
    errorElement.textContent = '❌ ' + message;
    document.body.appendChild(errorElement);
    setTimeout(() => { errorElement.remove(); }, 5000);
}

// Mettre à jour les statistiques globales
function updateStats(stats) {
    if (stats.active_jobs !== undefined) {
        document.getElementById('active-jobs').textContent = stats.active_jobs;
    }
    if (stats.gpu_usage !== undefined) {
        document.getElementById('gpu-usage').textContent = stats.gpu_usage.toFixed(1) + '%';
    }
    if (stats.memory_usage !== undefined) {
        document.getElementById('memory-usage').textContent = (stats.memory_usage / (1024*1024*1024)).toFixed(2) + ' GB';
    }
}

// Mettre à jour périodiquement
setInterval(() => {
    Object.values(currentJobs).forEach(job => {
        updateJobStatus(job);
    });
}, 1000);

// Charger les jobs existants au démarrage
window.addEventListener('load', function() {
    fetch('/api/jobs?limit=10')
        .then(response => response.json())
        .then(data => {
            data.jobs.forEach(job => {
                currentJobs[job.job_id] = job;
                createJobElement(job);
            });
        });
});
