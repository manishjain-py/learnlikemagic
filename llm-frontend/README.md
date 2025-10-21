# Learn Like Magic - Frontend

React + TypeScript UI for the adaptive tutoring system.

## Architecture

```
llm-frontend/
├── src/
│   ├── App.tsx           # Main component with curriculum selection
│   ├── App.css           # Styles
│   ├── api.ts            # API client
│   ├── main.tsx          # Entry point
│   └── vite-env.d.ts     # TypeScript declarations
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── Dockerfile
```

## Technology Stack

- **React 18**: UI library
- **TypeScript**: Type safety
- **Vite**: Fast build tool and dev server
- **CSS3**: Styling (no framework)

## Setup

### Prerequisites
- Node.js 18+ and npm

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Backend URL (Optional)

By default, the frontend connects to `http://localhost:8000`. To change:

```bash
# Create .env.local
echo "VITE_API_URL=http://your-backend-url:8000" > .env.local
```

### 3. Start Development Server

```bash
npm run dev
```

Frontend runs at: http://localhost:3000

## Available Scripts

```bash
# Development server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Type checking
npm run type-check

# Linting
npm run lint
```

## User Flow

### 1. Curriculum Selection

**Subject Selection:**
- User sees available subjects for their curriculum (Grade 3, CBSE, India)
- Subjects: Mathematics, English
- Click a card to proceed

**Topic Selection:**
- After selecting subject, see available topics
- Example (Mathematics): Fractions, Multiplication
- Back button returns to subject selection

**Subtopic Selection:**
- After selecting topic, see available subtopics with descriptions
- Example (Fractions):
  - Comparing Like Denominators
  - Adding Like Denominators
- Each card shows guideline_id
- Select to start learning session

### 2. Learning Session

**Chat Interface:**
- Displays selected curriculum path in header
- Progress indicators:
  - Step counter (e.g., "Step 3/10")
  - Mastery bar (0-100%)
- Chat messages:
  - Tutor messages (teaching content)
  - Student replies
  - Expandable hints (if provided)
- Input box for student responses
- Submit button (Enter key supported)

**Progress Updates:**
- Mastery score updates after each response
- Step counter increments
- Routing decision shown ("Advance" or "Remediate")
- Last grading feedback visible

**Session End:**
- Triggered when mastery ≥ 85% or step_idx ≥ 10
- Summary card displays:
  - Steps completed
  - Final mastery score
  - Misconceptions identified
  - Suggestions for next steps
- "Start New Session" button returns to subject selection

## Component Structure

### App.tsx

Main component managing the entire user flow:

```typescript
// State management
const [selectionStep, setSelectionStep] = useState<
  'subject' | 'topic' | 'subtopic' | 'chat'
>('subject');

const [subjects, setSubjects] = useState<string[]>([]);
const [topics, setTopics] = useState<string[]>([]);
const [subtopics, setSubtopics] = useState<SubtopicInfo[]>([]);

const [selectedSubject, setSelectedSubject] = useState('');
const [selectedTopic, setSelectedTopic] = useState('');
const [selectedSubtopic, setSelectedSubtopic] = useState('');

// Session state
const [sessionId, setSessionId] = useState<string | null>(null);
const [messages, setMessages] = useState<Message[]>([]);
const [stepIdx, setStepIdx] = useState(0);
const [mastery, setMastery] = useState(0.0);
```

**Key Functions:**
- `handleSubjectSelect()`: Fetch topics for selected subject
- `handleTopicSelect()`: Fetch subtopics for selected topic
- `handleSubtopicSelect()`: Create session with guideline_id
- `handleSubmit()`: Send student reply to backend
- `handleBack()`: Navigate backward through selection flow
- `resetToSelection()`: Return to subject selection

### api.ts

API client with TypeScript interfaces and functions:

```typescript
// Core types
export interface Student { id: string; grade: number; prefs?: StudentPrefs }
export interface Goal {
  topic: string;
  syllabus: string;
  learning_objectives: string[];
  guideline_id: string;
}
export interface Turn { message: string; hints?: string[]; step_idx: number; mastery_score: number }

// API functions
export async function getCurriculum(params: {...}): Promise<CurriculumResponse>
export async function createSession(student: Student, goal: Goal): Promise<SessionResponse>
export async function submitStep(sessionId: string, reply: string): Promise<StepResponse>
export async function getSessionSummary(sessionId: string): Promise<SessionSummary>
```

### App.css

Styling for all UI elements:
- `.selection-container`: Layout for curriculum selection screens
- `.selection-grid`: Responsive grid for subject/topic/subtopic cards
- `.selection-card`: Individual card styling with hover effects
- `.chat-interface`: Learning session container
- `.progress-bar`: Visual mastery indicator
- `.message`: Chat message styling
- `.summary-card`: Session completion summary

## Configuration

### Curriculum Settings

Currently hardcoded in `App.tsx`:

```typescript
const COUNTRY = 'India';
const BOARD = 'CBSE';
const GRADE = 3;
```

**To support multiple curricula:**
1. Add curriculum selection screen before subject selection
2. Store selected country/board/grade in state
3. Pass to API calls

### API Base URL

Configured via environment variable:

```typescript
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
```

**Production:**
```bash
VITE_API_URL=https://api.learnlikemagic.com
```

## Styling

### Color Scheme

```css
--primary: #4A90E2 (Blue)
--primary-dark: #357ABD
--success: #5CB85C (Green)
--danger: #D9534F (Red)
--light-bg: #F8F9FA
--border: #DEE2E6
```

### Responsive Design

- Mobile-first approach
- Breakpoints:
  - Mobile: < 768px (1 column grid)
  - Tablet: 768px - 1024px (2 column grid)
  - Desktop: > 1024px (3 column grid)

### Typography

- Font: System font stack (sans-serif)
- Sizes:
  - Headings: 1.5rem - 2rem
  - Body: 1rem
  - Small text: 0.875rem

## Development

### Hot Module Replacement (HMR)

Vite provides instant updates during development:
- Edit `App.tsx` → changes reflect immediately
- Edit `App.css` → styles update without page reload
- Edit `api.ts` → components re-render

### TypeScript

Type checking runs during development:

```bash
# Manual type check
npm run type-check

# Watch mode
npx tsc --watch --noEmit
```

### API Integration

**Local Backend:**
```typescript
// Default - connects to localhost:8000
const API_BASE_URL = 'http://localhost:8000';
```

**Remote Backend:**
```bash
# .env.local
VITE_API_URL=http://192.168.1.100:8000
```

### Debugging

**Browser DevTools:**
- React DevTools extension recommended
- Network tab for API call inspection
- Console for errors and logs

**Common Issues:**

1. **CORS errors:**
   - Ensure backend has CORS middleware configured
   - Check API_BASE_URL is correct

2. **API not responding:**
   - Verify backend is running on port 8000
   - Check network connectivity

3. **Type errors:**
   - Run `npm run type-check`
   - Ensure API responses match TypeScript interfaces

## Building for Production

### Build Process

```bash
npm run build
```

Output: `dist/` directory with optimized assets

**Build optimizations:**
- Code splitting
- Tree shaking
- Minification
- Asset hashing

### Preview Production Build

```bash
npm run preview
```

Serves the `dist/` folder at http://localhost:4173

### Deployment

**Static Hosting (Vercel, Netlify, etc.):**

```bash
# Build command
npm run build

# Output directory
dist

# Environment variables
VITE_API_URL=https://api.production.com
```

**Docker:**

```bash
# Build image
docker build -t llm-frontend .

# Run container
docker run -p 3000:3000 -e VITE_API_URL=http://api:8000 llm-frontend
```

**Docker Compose (with backend):**
```bash
# From project root
docker-compose up --build
```

## Features

### Current Features

- Multi-screen curriculum selection flow
- Subject → Topic → Subtopic navigation
- Back navigation between screens
- Real-time chat interface
- Progress visualization (step counter + mastery bar)
- Expandable hints
- Session summary with recommendations
- Responsive design (mobile-friendly)

### Planned Enhancements

- Persistent session storage (localStorage)
- Animation transitions between screens
- Loading states for API calls
- Error boundary for graceful error handling
- Accessibility improvements (ARIA labels, keyboard nav)
- Dark mode toggle
- Voice input for younger learners
- Gamification (badges, progress animations)

## Accessibility

### Current Support

- Semantic HTML elements
- Keyboard navigation (Enter to submit)
- Focus styles on interactive elements

### Improvements Needed

- ARIA labels for screen readers
- Skip navigation links
- High contrast mode
- Reduced motion support
- Keyboard shortcuts documentation

## Performance

### Bundle Size

Production build analysis:

```bash
npm run build

# Analyze with rollup-plugin-visualizer
npx vite-bundle-visualizer
```

Current bundle: ~150KB (gzipped)

### Optimization Tips

1. **Code splitting:**
   ```typescript
   const ChatInterface = lazy(() => import('./ChatInterface'));
   ```

2. **Memoization:**
   ```typescript
   const MemoizedCard = React.memo(SelectionCard);
   ```

3. **Debounce input:**
   ```typescript
   const debouncedSubmit = useMemo(
     () => debounce(handleSubmit, 300),
     []
   );
   ```

## Testing

### Manual Testing Checklist

- [ ] Subject selection loads correctly
- [ ] Topic selection shows topics for selected subject
- [ ] Subtopic selection shows subtopics for selected topic
- [ ] Session starts when subtopic is selected
- [ ] Chat messages display correctly
- [ ] Student replies are submitted
- [ ] Progress indicators update
- [ ] Back navigation works at each step
- [ ] Session summary appears at completion
- [ ] "Start New Session" resets to subject selection

### Automated Testing (Future)

```bash
# Install testing libraries
npm install -D vitest @testing-library/react @testing-library/user-event

# Run tests
npm run test
```

## Troubleshooting

### Port 3000 already in use

```bash
# Kill process on port 3000
lsof -ti:3000 | xargs kill -9

# Or use different port
npm run dev -- --port 3001
```

### Module not found errors

```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

### API connection fails

1. Check backend is running: `curl http://localhost:8000`
2. Verify VITE_API_URL is correct
3. Check browser console for CORS errors
4. Ensure backend CORS allows `http://localhost:3000`

### Build fails

```bash
# Clear Vite cache
rm -rf node_modules/.vite

# Reinstall dependencies
npm install

# Rebuild
npm run build
```

## Browser Support

**Supported:**
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Not supported:**
- Internet Explorer (deprecated)

## Contributing

When modifying frontend:

1. **Component changes:**
   - Keep components in `App.tsx` until codebase grows
   - Extract reusable components to separate files

2. **Styling:**
   - Follow existing CSS naming conventions
   - Use CSS variables for colors
   - Maintain responsive design

3. **API changes:**
   - Update TypeScript interfaces in `api.ts`
   - Add error handling for new endpoints
   - Document new API functions

4. **Testing:**
   - Test on multiple screen sizes
   - Verify keyboard navigation
   - Check API integration with backend

## Support

For frontend-specific issues:
- Check browser console for errors
- Verify API responses in Network tab
- Review API documentation at http://localhost:8000/docs
- Ensure backend is running and accessible

---

**Frontend Version**: 2.0
**Last Updated**: 2025-10-21
