# CrisisNexus — AI-Powered Rapid Crisis Response Platform

## Overview
CrisisNexus is a professional, submission-ready single-page web application demonstrating India's AI-first emergency response platform. It features scroll animations, interactive dashboards, a working crisis report form, SOS modal, and AI triage simulation.

## Architecture
- **Single HTML file**: `index.html` — all CSS, HTML, and JavaScript inline
- **Server**: Python 3 built-in HTTP server on port 5000
- **No external dependencies** beyond Google Fonts CDN

## Pages / Sections

### Overview (Landing)
- Animated hero with particle canvas background, grid overlay, gradient glows
- Animated stat counters (incidents, triage speed, lives assisted)
- 8-feature grid with scroll-triggered fade-up animations
- "How It Works" 4-step workflow section
- Interactive SOS panic button section
- Google AI Tech Stack pills
- Footer

### Command Center (Dashboard)
- Sidebar navigation with live badge counts
- KPI cards (critical incidents, response time, triage speed, volunteers)
- Live crisis map (styled grid with color-coded incident pins + units)
- Active incidents list with severity badges
- Gemini AI Triage Feed with confidence bars
- Resource allocation bars (ambulances, fire, hospital beds, blood, rescue)
- AI-matched volunteer list with dispatch buttons
- Live clock, refresh functionality

### Report Crisis (Form)
- Crisis type selector grid (6 types)
- Multilingual voice report (8 Indian languages) with recording simulation & waveform animation
- Incident details form (location, severity, description, casualties, contact)
- AI Photo Triage upload zone with Gemini Vision simulation (<3s analysis)
- Submit button with dispatch simulation and toast notification

### AI Analytics
- KPI metrics (triage time, prediction accuracy, lives assisted, offline syncs)
- Bar chart (incidents by type, animated on load)
- Donut chart (severity distribution)
- Vertex AI predictive alerts (4 risk cards)
- AI stack performance metrics (6 metric cards)

## Key Features
- Scroll-triggered animations via Intersection Observer API
- Particle canvas on hero with connection lines
- SOS modal with progress animation and GPS simulation
- Toast notifications for all interactions
- Topbar scroll blur effect
- Volunteer dispatch with state changes
- Live clock and simulated real-time KPI updates
- Fully responsive design

## Server
- Command: `python3 -m http.server 5000`
- Port: 5000 (webview)
