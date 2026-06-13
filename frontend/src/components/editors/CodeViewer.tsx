import { useState, useEffect, useRef, useMemo } from 'react'
import { Card, Button, Space, Tag, Typography, Alert, Spin, Tooltip, Dropdown, Collapse, Input, message } from 'antd'
import {
  PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined,
  DownloadOutlined, CloudUploadOutlined, DownOutlined,
  FileOutlined, FolderOutlined, FolderOpenOutlined,
  BulbOutlined, ReloadOutlined, LoadingOutlined, GithubOutlined,
  CopyOutlined,
} from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import type { ValidationResult, ExecutionResult, TestCase } from '@/types'
import { pipelineApi, integrationsApi, githubApi } from '@/api/client'

const { Text, Title } = Typography

// ── pytest output parser ──────────────────────────────────────────────────────

interface TestResult {
  id: string        // e.g. "tests/test_login.py::TestLogin::test_tc001"
  name: string      // short display name
  status: 'passed' | 'failed' | 'error'
  detail?: string   // failure traceback
}

function parsePytestOutput(stdout: string): TestResult[] {
  const results: TestResult[] = []
  const lines = stdout.split('\n')

  // A test node ID starts a line: "tests/foo.py::Class::method" or "tests/foo.py::method"
  // Path chars: word chars + / \ .
  const nodeStartRe = /^([\w/\\.][\w/\\.]*::[\w:]+)/

  // With -v (no -s): ID and status are on the SAME line:
  //   "tests/foo.py::Class::test_name PASSED  [ 50%]"
  // With -v -s: pytest writes the ID, then print() output goes to stdout (on the
  // same line or next lines), then pytest writes "PASSED" on a NEW line.
  //   "tests/foo.py::Class::test_name ▶ Step 1..."  <- ID line
  //   "✓ Step 1 done"                                <- print output
  //   "PASSED  [ 50%]"                               <- status on its own line
  // The parser below handles BOTH formats.

  let pendingId: string | null = null
  let pendingName: string | null = null

  for (const line of lines) {
    const nodeMatch = line.match(nodeStartRe)

    if (nodeMatch) {
      const id = nodeMatch[1]
      const rest = line.slice(nodeMatch[0].length)
      const parts = id.split('::')
      const name = parts[parts.length - 1]

      // Check whether the status follows immediately on the same line
      // (separated only by spaces and optional percentage — no other words).
      // We require the status to appear with only spaces/percent before it so
      // a print like "Step 1: task PASSED" doesn't falsely match.
      const inlineStatus = rest.match(/^\s+(PASSED|FAILED|ERROR)\b/)
      if (inlineStatus) {
        if (!results.find(r => r.id === id)) {
          results.push({ id, name, status: inlineStatus[1].toLowerCase() as TestResult['status'] })
        }
        pendingId = null
        pendingName = null
      } else {
        // Status will arrive on a later line (happens with -s flag)
        pendingId = id
        pendingName = name
      }
      continue
    }

    // Look for a standalone status line for the pending test.
    // Allow optional leading whitespace and trailing [percent] noise.
    if (pendingId !== null) {
      const statusMatch = line.match(/^\s*(PASSED|FAILED|ERROR)\b/)
      if (statusMatch) {
        if (!results.find(r => r.id === pendingId)) {
          results.push({
            id: pendingId,
            name: pendingName!,
            status: statusMatch[1].toLowerCase() as TestResult['status'],
          })
        }
        pendingId = null
        pendingName = null
      }
      // Keep pendingId while we're reading print output lines
    }
  }

  // Extract failure/error tracebacks.
  // Pytest separator format: "_____ ClassName::test_name _____"
  const blockRe = /_{5,}\s+(.+?)\s+_{5,}\n([\s\S]*?)(?=_{5,}|\n={5,}|$)/g
  for (const blockMatch of stdout.matchAll(blockRe)) {
    const header  = blockMatch[1].trim()
    const content = blockMatch[2].trim()
    if (!content) continue

    const result = results.find(r => {
      const segments = r.id.split('::')
      const tail2 = segments.slice(-2).join('::')
      const tail1 = segments[segments.length - 1]
      return header === tail2 || header.endsWith(tail1) || tail2.endsWith(header)
    })
    if (result) result.detail = content
  }

  return results
}

// ── live output parser ────────────────────────────────────────────────────────

interface LiveTestResult {
  id: string
  name: string
  status: 'running' | 'passed' | 'failed' | 'error'
}

/**
 * Incrementally parse streaming pytest stdout lines to get per-test live status.
 * A test is 'running' from the moment its ID appears until PASSED/FAILED/ERROR is seen.
 * Handles both inline format (-v) and split format (-v -s with print output).
 */
function parseLiveOutput(lines: string[]): LiveTestResult[] {
  const nodeStartRe = /^([\w/\\.][\w/\\.]*::[\w:]+)/
  const results: LiveTestResult[] = []
  let pendingId: string | null = null
  let pendingName: string | null = null

  for (const line of lines) {
    const nodeMatch = line.match(nodeStartRe)
    if (nodeMatch) {
      const id = nodeMatch[1]
      const rest = line.slice(nodeMatch[0].length)
      const parts = id.split('::')
      const name = parts[parts.length - 1]
      const inlineStatus = rest.match(/^\s+(PASSED|FAILED|ERROR)\b/)

      if (inlineStatus) {
        const status = inlineStatus[1].toLowerCase() as LiveTestResult['status']
        const existing = results.find(r => r.id === id)
        if (existing) existing.status = status
        else results.push({ id, name, status })
        pendingId = null; pendingName = null
      } else {
        // Test started — mark as running until we see its status
        if (!results.find(r => r.id === id)) results.push({ id, name, status: 'running' })
        pendingId = id; pendingName = name
      }
      continue
    }

    if (pendingId !== null) {
      const statusMatch = line.match(/^\s*(PASSED|FAILED|ERROR)\b/)
      if (statusMatch) {
        const status = statusMatch[1].toLowerCase() as LiveTestResult['status']
        const existing = results.find(r => r.id === pendingId)
        if (existing) existing.status = status
        else results.push({ id: pendingId, name: pendingName!, status })
        pendingId = null; pendingName = null
      }
    }
  }
  return results
}

// ── test-case matcher ─────────────────────────────────────────────────────────

/**
 * Best-effort match between a pytest test function name and a TestCase object.
 * Tries TC-ID extraction first, then falls back to keyword overlap.
 */
function matchTestCase(testName: string, testCases: TestCase[]): TestCase | null {
  if (!testCases.length) return null

  // 1. TC ID embedded in function name: test_tc001, test_tc_002, test_003_login
  const tcNum = testName.match(/(?:tc[_-]?)(\d{1,4})/i)?.[1]
  if (tcNum) {
    const padded = tcNum.padStart(3, '0')
    const found = testCases.find(tc =>
      tc.id.replace(/\D/g, '').padStart(3, '0') === padded
    )
    if (found) return found
  }

  // 2. Keyword overlap between snake_case function name and title words
  const fnWords = new Set(testName.toLowerCase().split('_').filter(w => w.length > 3))
  let best: TestCase | null = null
  let bestScore = 0
  for (const tc of testCases) {
    const titleWords = new Set(tc.title.toLowerCase().split(/\W+/).filter(w => w.length > 3))
    const overlap = [...fnWords].filter(w => titleWords.has(w)).length
    const score = overlap / Math.max(fnWords.size, titleWords.size, 1)
    if (score > bestScore && score >= 0.25) { bestScore = score; best = tc }
  }
  return best
}

interface Props {
  sessionId: string
  generatedTests: Record<string, string>
  validationResults: ValidationResult[]
  executions: ExecutionResult[]
  testCases?: TestCase[]
  executionOutput?: string[]
  onExecute: () => Promise<void>
  onExecuteFile?: (testNode: string) => Promise<void>
  loading?: boolean
}

// Structured diagnosis returned by the explain-failure endpoint
interface ExplainResult {
  failed_step: string
  root_cause: string
  fix: string
  code_example: string
}

// State for AI explain/regenerate/run actions per test ID
interface TestActionState {
  explaining: boolean
  explanation?: ExplainResult
  regenerating: boolean
  regenerated: boolean    // true after a successful regeneration — shows badge
  feedback: string        // user input: what to fix
}

// Build a tree structure from flat file paths
interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children: TreeNode[]
}

function buildTree(files: string[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', isDir: true, children: [] }

  for (const filepath of files) {
    const parts = filepath.split('/')
    let node = root
    let currentPath = ''
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      currentPath = currentPath ? `${currentPath}/${part}` : part
      const isLast = i === parts.length - 1
      let child = node.children.find(c => c.name === part)
      if (!child) {
        child = { name: part, path: currentPath, isDir: !isLast, children: [] }
        node.children.push(child)
      }
      node = child
    }
  }

  return root.children
}

function FileTree({
  nodes,
  selectedFile,
  onSelect,
  validationByFile,
  openFolders,
  onToggleFolder,
  depth = 0,
}: {
  nodes: TreeNode[]
  selectedFile: string
  onSelect: (path: string) => void
  validationByFile: Record<string, ValidationResult>
  openFolders: Set<string>
  onToggleFolder: (path: string) => void
  depth?: number
}) {
  return (
    <div>
      {nodes.map(node => {
        const isOpen = openFolders.has(node.path)
        const validation = validationByFile[node.path]
        const isActive = node.path === selectedFile

        if (node.isDir) {
          return (
            <div key={node.path}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '3px 6px',
                  paddingLeft: 8 + depth * 16,
                  cursor: 'pointer',
                  borderRadius: 4,
                  fontSize: 12,
                  color: '#ccc',
                  userSelect: 'none',
                }}
                onClick={() => onToggleFolder(node.path)}
              >
                {isOpen
                  ? <FolderOpenOutlined style={{ color: '#e8b339', fontSize: 13 }} />
                  : <FolderOutlined style={{ color: '#e8b339', fontSize: 13 }} />
                }
                <span>{node.name}</span>
              </div>
              {isOpen && (
                <FileTree
                  nodes={node.children}
                  selectedFile={selectedFile}
                  onSelect={onSelect}
                  validationByFile={validationByFile}
                  openFolders={openFolders}
                  onToggleFolder={onToggleFolder}
                  depth={depth + 1}
                />
              )}
            </div>
          )
        }

        return (
          <div
            key={node.path}
            onClick={() => onSelect(node.path)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 6px',
              paddingLeft: 8 + depth * 16,
              cursor: 'pointer',
              borderRadius: 4,
              fontSize: 12,
              background: isActive ? '#1f3864' : 'transparent',
              color: isActive ? '#fff' : '#ccc',
              userSelect: 'none',
            }}
          >
            <FileOutlined style={{ fontSize: 12, flexShrink: 0 }} />
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {node.name}
            </span>
            {validation && (
              validation.passed
                ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />
                : <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function CodeViewer({
  sessionId,
  generatedTests,
  validationResults,
  executions,
  testCases = [],
  executionOutput = [],
  onExecute,
  onExecuteFile,
  loading,
}: Props) {
  const files = Object.keys(generatedTests)
  const [activeFile, setActiveFile] = useState<string>(files[0] ?? '')
  const [syncing, setSyncing] = useState(false)
  const [pushingGitHub, setPushingGitHub] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    const content = generatedTests[activeFile]
    if (!content) return
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  const terminalRef = useRef<HTMLDivElement>(null)

  // Live per-test status derived from streaming output lines
  const liveResults = useMemo(() => parseLiveOutput(executionOutput), [executionOutput])

  // Controlled expansion for the execution runs Collapse.
  // Auto-expand the latest run whenever a new one appears.
  const [expandedRuns, setExpandedRuns] = useState<string[]>([])
  const prevRunCountRef = useRef(0)
  useEffect(() => {
    if (executions.length > prevRunCountRef.current && executions.length > 0) {
      const latestKey = executions[0].id ?? executions[0].created_at ?? 'run-0'
      setExpandedRuns(prev => (prev.includes(latestKey) ? prev : [latestKey, ...prev]))
    }
    prevRunCountRef.current = executions.length
  }, [executions.length])

  // Per-test AI action state (keyed by test result ID)
  const [testActions, setTestActions] = useState<Record<string, TestActionState>>({})

  // Set when any file is regenerated — prompts user to re-run the full suite
  // to catch regressions in other tests that depend on the changed file.
  const [regressionWarning, setRegressionWarning] = useState<string | null>(null)

  const setTestAction = (id: string, patch: Partial<TestActionState>) => {
    setTestActions(prev => ({
      ...prev,
      [id]: { ...{ explaining: false, regenerating: false, regenerated: false, feedback: '' }, ...prev[id], ...patch },
    }))
  }

  const handleExplain = async (r: TestResult, tc: TestCase | null) => {
    if (!r.detail) return
    setTestAction(r.id, { explaining: true })
    try {
      const tcPayload = tc ? { title: tc.title, steps: tc.steps, preconditions: tc.preconditions } : null
      const res = await pipelineApi.explainFailure(sessionId, r.name, r.detail, tcPayload as Record<string, unknown> | null)
      setTestAction(r.id, { explaining: false, explanation: res.explanation })
    } catch {
      setTestAction(r.id, {
        explaining: false,
        explanation: { failed_step: 'Failed to get explanation.', root_cause: '', fix: 'Try again.', code_example: '' },
      })
    }
  }

  // Find the actual file that needs to be fixed.
  // Strategy: scan the traceback for file paths that exist in generatedTests,
  // take the deepest one (closest to root cause — often a page object, not the test).
  // Falls back to searching by function name in test files, then the first test file.
  const findFailingFile = (testName: string, traceback: string): string => {
    // Match "path/to/file.py:line" patterns — only local files, not site-packages
    const matches = Array.from(traceback.matchAll(/^([\w./][\w./]*\.py):\d+/gm))
    const tracebackPaths = matches.map(m => m[1]).filter(p => !p.startsWith('/'))

    // Last generated file in the traceback = deepest local frame = root cause
    for (let i = tracebackPaths.length - 1; i >= 0; i--) {
      if (generatedTests[tracebackPaths[i]]) return tracebackPaths[i]
    }
    // Fallback: find test file by function name
    for (const [filepath, code] of Object.entries(generatedTests)) {
      if (filepath.startsWith('tests/') && code.includes(`def ${testName}`)) return filepath
    }
    return files.find(f => f.startsWith('tests/')) ?? files[0] ?? ''
  }

  // Build a full pytest node id from a TestResult id (e.g. "tests/test_cart.py::TestCart::test_add")
  const toTestNode = (r: TestResult): string => r.id

  const handleRegenerate = async (r: TestResult, tc: TestCase | null) => {
    if (!r.detail) return
    const filename = findFailingFile(r.name, r.detail)
    if (!filename) return

    const state = testActions[r.id]
    const userFeedback = state?.feedback?.trim() ?? ''
    const diagnosis = state?.explanation

    // Serialize AI diagnosis into a detailed block (includes code_example).
    const diagnosisBlock = diagnosis
      ? [
          `Root cause: ${diagnosis.root_cause}`,
          `Suggested fix: ${diagnosis.fix}`,
          diagnosis.code_example ? `Code example:\n${diagnosis.code_example}` : '',
        ].filter(Boolean).join('\n')
      : ''

    // Build effective feedback: human input takes precedence, AI diagnosis fills the gap.
    // If both are present, combine so the LLM has full context.
    let effectiveFeedback: string | undefined
    if (userFeedback && diagnosisBlock) {
      effectiveFeedback = `${userFeedback}\n\nAI diagnosis:\n${diagnosisBlock}`
    } else if (userFeedback) {
      effectiveFeedback = userFeedback
    } else if (diagnosisBlock) {
      effectiveFeedback = diagnosisBlock
    }

    setTestAction(r.id, { regenerating: true })
    try {
      const tcPayload = tc ? { title: tc.title, steps: tc.steps, preconditions: tc.preconditions } : null
      await pipelineApi.regenerateTest(sessionId, filename, r.detail, tcPayload as Record<string, unknown> | null, effectiveFeedback)
      setTestAction(r.id, { regenerating: false, regenerated: true })
      setRegressionWarning(filename)
    } catch {
      setTestAction(r.id, { regenerating: false })
    }
  }

  // Scroll only within the terminal box — never yank the page
  useEffect(() => {
    const el = terminalRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [executionOutput.length])

  // Start with all folders open — lazy initializer runs only once
  const [openFolders, setOpenFolders] = useState<Set<string>>(() => {
    const folders = new Set<string>()
    for (const f of files) {
      const parts = f.split('/')
      let p = ''
      for (let i = 0; i < parts.length - 1; i++) {
        p = p ? `${p}/${parts[i]}` : parts[i]
        folders.add(p)
      }
    }
    return folders
  })

  const toggleFolder = (path: string) => {
    setOpenFolders(prev => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })
  }

  const validationByFile = Object.fromEntries(
    validationResults.map(r => [r.filename, r])
  )

  // Data/helper modules that live in tests/ but are not test suites
  const DATA_MODULE_NAMES = ['test_data.py', 'test_helpers.py', 'test_utils.py', 'test_fixtures.py']
  // Only count actual test files in the pass check — data modules, __init__.py, conftest, etc. are excluded
  const testResults = validationResults.filter(r => {
    const basename = r.filename.split('/').pop() ?? r.filename
    if (DATA_MODULE_NAMES.includes(basename)) return false
    return r.filename.includes('test_') || r.filename.includes('/test')
  })
  const allPassed = testResults.length > 0
    ? testResults.every(r => r.passed)
    : validationResults.length > 0 && validationResults.every(r => r.passed)
  // Allow running if there are generated tests and validation either passed or hasn't run yet.
  // Only block execution when validation has explicitly flagged failures.
  const validationFailed = validationResults.length > 0 && !allPassed
  const canRun = files.length > 0 && !validationFailed
  const tree = buildTree(files)

  const handleSyncAzure = async () => {
    setSyncing(true)
    try {
      const result = await integrationsApi.syncToAzure(sessionId, 'TestFlow AI')
      message.success(`Synced ${result.test_cases_synced} test case(s) to Azure DevOps`)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ?? 'Failed to sync to Azure DevOps')
    } finally {
      setSyncing(false)
    }
  }

  const handlePushGitHub = async () => {
    setPushingGitHub(true)
    try {
      const result = await githubApi.push(sessionId)
      message.success(`Pushed ${result.pushed_count} file(s) to ${result.repo} (${result.branch})`)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ?? 'Failed to push to GitHub')
    } finally {
      setPushingGitHub(false)
    }
  }

  const downloadMenuItems = [
    {
      key: 'zip',
      label: 'Download as ZIP',
      icon: <DownloadOutlined />,
      onClick: () => pipelineApi.downloadZip(sessionId),
    },
    {
      key: 'github-actions',
      label: 'GitHub Actions workflow',
      icon: <DownloadOutlined />,
      onClick: () => pipelineApi.downloadGithubActions(sessionId),
    },
    {
      key: 'azure-pipeline',
      label: 'Azure Pipelines YAML',
      icon: <DownloadOutlined />,
      onClick: () => pipelineApi.downloadAzurePipelines(sessionId),
    },
    { type: 'divider' as const },
    {
      key: 'push-github',
      label: pushingGitHub ? 'Pushing...' : 'Push to GitHub',
      icon: <GithubOutlined />,
      onClick: handlePushGitHub,
      disabled: pushingGitHub,
    },
  ]

  const activeValidation = validationByFile[activeFile]

  return (
    <Card
      styles={{ body: { padding: 0 } }}
      title={
        <Space>
          <Title level={5} style={{ margin: 0 }}>Generated Tests</Title>
          <Tag color="default">{files.length} file{files.length !== 1 ? 's' : ''}</Tag>
          {allPassed && <Tag color="green">All valid</Tag>}
        </Space>
      }
      extra={
        <Space>
          <Dropdown menu={{ items: downloadMenuItems }} trigger={['click']}>
            <Button size="small" icon={<DownloadOutlined />}>
              Export <DownOutlined />
            </Button>
          </Dropdown>
          <Tooltip title="Sync test cases to Azure DevOps">
            <Button
              size="small"
              icon={<CloudUploadOutlined />}
              onClick={handleSyncAzure}
              loading={syncing}
            >
              Azure DevOps
            </Button>
          </Tooltip>
          <Tooltip title={validationFailed ? 'Fix validation errors before running' : 'Run tests with pytest'}>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={onExecute}
              loading={loading}
              disabled={!canRun}
            >
              Run Tests
            </Button>
          </Tooltip>
        </Space>
      }
    >
      {/* Regression warning — shown after any file regeneration */}
      {regressionWarning && (
        <Alert
          type="warning"
          showIcon
          style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderTop: 'none' }}
          message={
            <Space>
              <span>
                <strong>{regressionWarning}</strong> was regenerated.
                Run the full suite to check no other tests broke.
              </span>
              <Button
                size="small"
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={loading}
                disabled={!canRun}
                onClick={() => { setRegressionWarning(null); onExecute() }}
              >
                Run All Tests
              </Button>
              <Button size="small" onClick={() => setRegressionWarning(null)}>Dismiss</Button>
            </Space>
          }
          closable={false}
        />
      )}

      {/* Repo-style layout: sidebar + editor */}
      <div style={{ display: 'flex', height: 480 }}>
        {/* File tree sidebar */}
        <div
          style={{
            width: 200,
            flexShrink: 0,
            background: '#1e1e1e',
            borderRight: '1px solid #333',
            overflowY: 'auto',
            padding: '8px 4px',
          }}
        >
          <div style={{ fontSize: 10, color: '#666', padding: '0 6px 6px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Explorer
          </div>
          <FileTree
            nodes={tree}
            selectedFile={activeFile}
            onSelect={setActiveFile}
            validationByFile={validationByFile}
            openFolders={openFolders}
            onToggleFolder={toggleFolder}
          />
        </div>

        {/* Editor pane */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tab bar / breadcrumb */}
          <div
            style={{
              background: '#252526',
              borderBottom: '1px solid #333',
              padding: '4px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              minHeight: 32,
            }}
          >
            {activeFile ? (
              <>
                <FileOutlined style={{ color: '#9cdcfe', fontSize: 12 }} />
                <Text style={{ fontSize: 12, color: '#ccc' }}>{activeFile}</Text>
                {activeValidation && (
                  activeValidation.passed
                    ? <Tag color="green" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>valid</Tag>
                    : <Tag color="red" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>errors</Tag>
                )}
                <Tooltip title={copied ? 'Copied!' : 'Copy file contents'}>
                  <Button
                    type="text"
                    size="small"
                    icon={<CopyOutlined />}
                    onClick={handleCopy}
                    style={{
                      marginLeft: 'auto',
                      color: copied ? '#3fb950' : '#666',
                      fontSize: 12,
                    }}
                  >
                    {copied ? 'Copied' : ''}
                  </Button>
                </Tooltip>
              </>
            ) : (
              <Text style={{ fontSize: 12, color: '#666' }}>No file selected</Text>
            )}
          </div>

          {/* Validation alerts */}
          {activeValidation && !activeValidation.passed && (
            <Alert
              type="error"
              message="Validation errors"
              description={
                <ul style={{ paddingLeft: 16, margin: 0 }}>
                  {activeValidation.errors.map((e, i) => (
                    <li key={i}><Text code style={{ fontSize: 11 }}>{e}</Text></li>
                  ))}
                </ul>
              }
              style={{ margin: '4px 8px', flexShrink: 0 }}
            />
          )}
          {(activeValidation?.warnings ?? []).length > 0 && (
            <Alert
              type="warning"
              message={
                <ul style={{ paddingLeft: 16, margin: 0 }}>
                  {(activeValidation?.warnings ?? []).map((w, i) => (
                    <li key={i}><Text style={{ fontSize: 11 }}>{w}</Text></li>
                  ))}
                </ul>
              }
              style={{ margin: '4px 8px', flexShrink: 0 }}
            />
          )}

          {/* Monaco editor */}
          <div style={{ flex: 1, minHeight: 0 }}>
            {activeFile && generatedTests[activeFile] ? (
              <Editor
                height="100%"
                language="python"
                value={generatedTests[activeFile]}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'off',
                  padding: { top: 8 },
                }}
              />
            ) : (
              <div
                style={{
                  height: '100%',
                  background: '#1e1e1e',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Text style={{ color: '#555', fontSize: 13 }}>Select a file to view</Text>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Execution results */}
      {(executions.length > 0 || loading) && (
        <div style={{ padding: 12, borderTop: '1px solid #f0f0f0' }}>

          {/* ── Live run panel (shown only while running) ── */}
          {loading && (
            <div style={{ marginBottom: executions.length > 0 ? 16 : 0 }}>

              {/* Live per-test status — expandable list */}
              {liveResults.length > 0 && (
                <Card
                  size="small"
                  style={{ marginBottom: 8 }}
                  styles={{ body: { padding: '4px 0' } }}
                  title={
                    <Space size={8}>
                      <Spin size="small" />
                      <Text strong style={{ fontSize: 13 }}>Running tests</Text>
                      <Tag color="processing">{liveResults.filter(r => r.status === 'running').length} running</Tag>
                      {liveResults.filter(r => r.status === 'passed').length > 0 && (
                        <Tag color="success">{liveResults.filter(r => r.status === 'passed').length} passed</Tag>
                      )}
                      {liveResults.filter(r => r.status !== 'running' && r.status !== 'passed').length > 0 && (
                        <Tag color="error">{liveResults.filter(r => r.status !== 'running' && r.status !== 'passed').length} failed</Tag>
                      )}
                    </Space>
                  }
                >
                  {liveResults.map(r => {
                    const isRunning = r.status === 'running'
                    const isPassed  = r.status === 'passed'
                    const icon = isRunning
                      ? <LoadingOutlined style={{ color: '#1677ff', fontSize: 13 }} />
                      : isPassed
                        ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} />
                        : <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 13 }} />
                    return (
                      <div
                        key={r.id}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          padding: '5px 12px',
                          background: isRunning ? '#e6f4ff' : isPassed ? '#f6ffed' : '#fff2f0',
                          borderBottom: '1px solid #f0f0f0',
                        }}
                      >
                        {icon}
                        <Text style={{ fontSize: 12, flex: 1 }}>{r.name}</Text>
                        <Tag
                          color={isRunning ? 'processing' : isPassed ? 'success' : 'error'}
                          style={{ margin: 0, fontSize: 10 }}
                        >
                          {r.status}
                        </Tag>
                      </div>
                    )
                  })}
                </Card>
              )}

              {/* Raw terminal output — collapsible, open by default */}
              <Collapse
                size="small"
                defaultActiveKey={['terminal']}
                items={[{
                  key: 'terminal',
                  label: (
                    <Space size={6}>
                      <Text style={{ fontSize: 12 }}>Raw output</Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {executionOutput.length} line{executionOutput.length !== 1 ? 's' : ''}
                      </Text>
                    </Space>
                  ),
                  children: (
                    <div
                      ref={terminalRef}
                      style={{
                        background: '#0d1117',
                        padding: '10px 14px',
                        minHeight: 40,
                        maxHeight: 220,
                        overflowY: 'auto',
                        fontFamily: '"Fira Code", "JetBrains Mono", Consolas, monospace',
                        fontSize: 12,
                      }}
                    >
                      {executionOutput.length === 0 ? (
                        <span style={{ color: '#484f58' }}>Waiting for pytest to start...</span>
                      ) : (
                        executionOutput.map((line, i) => {
                          const isPassed  = /\bPASSED\b/.test(line)
                          const isFailed  = /\bFAILED\b|ERROR/.test(line)
                          const isSummary = /passed|failed|error/.test(line) && line.includes('=')
                          const color = isPassed ? '#3fb950' : isFailed ? '#f85149' : isSummary ? '#e3b341' : '#e6edf3'
                          return (
                            <div key={i} style={{ color, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                              {line || '\u00a0'}
                            </div>
                          )
                        })
                      )}
                    </div>
                  ),
                }]}
              />

              {/* Spinner fallback when pytest hasn't emitted any test IDs yet */}
              {liveResults.length === 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
                  <Spin size="small" />
                  <Text type="secondary" style={{ fontSize: 12 }}>Waiting for pytest to start...</Text>
                </div>
              )}
            </div>
          )}
          {executions.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>Test Runs</Text>
                <Tag color="default">{executions.length} run{executions.length !== 1 ? 's' : ''}</Tag>
                {loading && <Spin size="small" />}
              </div>
              <Collapse
                size="small"
                activeKey={expandedRuns}
                onChange={keys => setExpandedRuns(keys as string[])}
                items={executions.map((exec, idx) => {
                  const parsed = parsePytestOutput(exec.stdout ?? '')
                  const ts = exec.created_at
                    ? new Date(exec.created_at).toLocaleTimeString()
                    : `Run ${executions.length - idx}`
                  // Stable key: prefer DB id, fall back to created_at, then index
                  const runKey = exec.id ?? exec.created_at ?? `run-${idx}`
                  return {
                    key: runKey,
                    label: (
                      <Space size={8}>
                        <Tag color={exec.status === 'passed' ? 'green' : 'red'} style={{ margin: 0 }}>
                          {exec.status}
                        </Tag>
                        <Text style={{ fontSize: 12 }}>
                          {exec.pass_count}/{exec.test_count} passed
                        </Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>{ts}</Text>
                      </Space>
                    ),
                    children: (
                      <>
                        {/* Every test is expandable — shows spec steps + traceback */}
                        {parsed.length > 0 && (
                          <Collapse
                            size="small"
                            style={{ marginTop: 4 }}
                            items={parsed.map((r, ri) => {
                              const tc = matchTestCase(r.name, testCases)
                              const icon = r.status === 'passed'
                                ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                                : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                              const actionState = testActions[r.id]
                            return {
                                // Use numeric index string — r.id contains "::" and "/" which
                                // can confuse Ant Design's internal key handling.
                                key: `${runKey}-t${ri}`,
                                label: (
                                  <Space size={6}>
                                    {icon}
                                    <Text style={{ fontSize: 12 }}>{r.name}</Text>
                                    {tc && (
                                      <Text type="secondary" style={{ fontSize: 11 }}>
                                        — {tc.title}
                                      </Text>
                                    )}
                                    {actionState?.regenerated && (
                                      <Tag
                                        color="cyan"
                                        style={{ margin: 0, fontSize: 10, fontStyle: 'italic' }}
                                      >
                                        regenerated
                                      </Tag>
                                    )}
                                  </Space>
                                ),
                                children: (
                                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                                    {/* Test case spec: preconditions + steps */}
                                    {tc && (
                                      <div>
                                        {tc.preconditions.length > 0 && (
                                          <div style={{ marginBottom: 6 }}>
                                            <Text type="secondary" style={{ fontSize: 11 }}>Preconditions</Text>
                                            <ul style={{ paddingLeft: 16, margin: '2px 0 0' }}>
                                              {tc.preconditions.map((p, i) => (
                                                <li key={i}><Text style={{ fontSize: 12 }}>{p}</Text></li>
                                              ))}
                                            </ul>
                                          </div>
                                        )}
                                        <Text type="secondary" style={{ fontSize: 11 }}>Steps</Text>
                                        <ol style={{ paddingLeft: 16, margin: '2px 0 0' }}>
                                          {tc.steps.map((s, i) => (
                                            <li key={i} style={{ marginBottom: 4 }}>
                                              <Text style={{ fontSize: 12 }}>{s.action}</Text>
                                              <br />
                                              <Text type="secondary" style={{ fontSize: 11 }}>
                                                → {s.expected_result}
                                              </Text>
                                            </li>
                                          ))}
                                        </ol>
                                      </div>
                                    )}
                                    {/* Failure traceback + AI actions */}
                                    {r.status !== 'passed' && (
                                      <div>
                                        {/* Action toolbar */}
                                        <Space wrap size={4} style={{ marginBottom: 8 }}>
                                          {r.detail && (
                                            <Tooltip title="Ask AI to explain why this test failed">
                                              <Button
                                                size="small"
                                                icon={<BulbOutlined />}
                                                loading={actionState?.explaining}
                                                disabled={loading}
                                                onClick={() => handleExplain(r, tc)}
                                              >
                                                Explain
                                              </Button>
                                            </Tooltip>
                                          )}
                                          {onExecuteFile && (
                                            <Tooltip title={`Run only ${r.name}`}>
                                              <Button
                                                size="small"
                                                type="primary"
                                                ghost
                                                icon={<PlayCircleOutlined />}
                                                disabled={loading}
                                                onClick={() => onExecuteFile(toTestNode(r))}
                                              >
                                                Run this test
                                              </Button>
                                            </Tooltip>
                                          )}
                                        </Space>

                                        {/* Structured AI diagnosis */}
                                        {actionState?.explanation && (
                                          <div style={{
                                            background: '#e6f4ff', border: '1px solid #91caff',
                                            borderRadius: 6, padding: '10px 12px', marginBottom: 8,
                                          }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                                              <BulbOutlined style={{ color: '#1677ff' }} />
                                              <Text strong style={{ fontSize: 12, color: '#1677ff' }}>AI Diagnosis</Text>
                                            </div>
                                            {actionState.explanation.failed_step && (
                                              <div style={{ marginBottom: 6 }}>
                                                <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.4px' }}>Failed step</Text>
                                                <div><Text style={{ fontSize: 12 }}>{actionState.explanation.failed_step}</Text></div>
                                              </div>
                                            )}
                                            {actionState.explanation.root_cause && (
                                              <div style={{ marginBottom: 6 }}>
                                                <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.4px' }}>Root cause</Text>
                                                <div><Text style={{ fontSize: 12 }}>{actionState.explanation.root_cause}</Text></div>
                                              </div>
                                            )}
                                            {actionState.explanation.fix && (
                                              <div style={{ marginBottom: 6 }}>
                                                <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.4px' }}>Fix</Text>
                                                <div><Text style={{ fontSize: 12 }}>{actionState.explanation.fix}</Text></div>
                                              </div>
                                            )}
                                            {actionState.explanation.code_example && (
                                              <div>
                                                <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.4px' }}>Example</Text>
                                                <pre style={{
                                                  background: '#0d1117', color: '#e6edf3',
                                                  padding: '6px 10px', borderRadius: 4,
                                                  fontSize: 11, margin: '4px 0 0',
                                                  whiteSpace: 'pre-wrap', overflowX: 'auto',
                                                }}>
                                                  {actionState.explanation.code_example}
                                                </pre>
                                              </div>
                                            )}
                                          </div>
                                        )}

                                        {/* Feedback input + Regenerate */}
                                        {r.detail && (
                                          <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
                                            <Input
                                              size="small"
                                              placeholder={
                                                actionState?.explanation
                                                  ? "Add instructions (AI diagnosis used by default)…"
                                                  : "What to fix (optional)…"
                                              }
                                              value={actionState?.feedback ?? ''}
                                              onChange={e => setTestAction(r.id, { feedback: e.target.value })}
                                              onPressEnter={() => handleRegenerate(r, tc)}
                                              disabled={actionState?.regenerating || loading}
                                              style={{ fontSize: 12 }}
                                            />
                                            <Tooltip title="Ask AI to regenerate the fixed test code">
                                              <Button
                                                size="small"
                                                icon={<ReloadOutlined />}
                                                loading={actionState?.regenerating}
                                                disabled={loading}
                                                onClick={() => handleRegenerate(r, tc)}
                                              >
                                                Regenerate
                                              </Button>
                                            </Tooltip>
                                          </Space.Compact>
                                        )}

                                        {/* Traceback */}
                                        <Text type="secondary" style={{ fontSize: 11 }}>Traceback</Text>
                                        {r.detail ? (
                                          <pre style={{
                                            background: '#fff2f0', padding: 8, borderRadius: 4,
                                            fontSize: 11, margin: '4px 0 0', overflowX: 'auto',
                                            whiteSpace: 'pre-wrap', color: '#cf1322',
                                          }}>
                                            {r.detail}
                                          </pre>
                                        ) : (
                                          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                                            No traceback captured. Check the raw stdout below.
                                          </Text>
                                        )}
                                      </div>
                                    )}
                                    {r.status === 'passed' && !tc && (
                                      <Text type="secondary" style={{ fontSize: 12 }}>
                                        No matching test spec found.
                                      </Text>
                                    )}
                                  </Space>
                                ),
                              }
                            })}
                          />
                        )}

                        {/* Fallback: if parser found no tests, show raw stdout so panel is never blank */}
                        {parsed.length === 0 && exec.stdout && (
                          <pre style={{
                            background: '#0d1117', color: '#e6edf3',
                            padding: 8, borderRadius: 4,
                            fontSize: 11, maxHeight: 200, overflow: 'auto',
                            marginTop: 4, whiteSpace: 'pre-wrap',
                          }}>
                            {exec.stdout}
                          </pre>
                        )}

                        {/* Stderr (infra errors, not test failures) */}
                        {exec.stderr && (
                          <pre style={{
                            background: '#fff2f0', padding: 8, borderRadius: 4,
                            fontSize: 11, maxHeight: 120, overflow: 'auto',
                            marginTop: 8, color: '#cf1322',
                          }}>
                            {exec.stderr}
                          </pre>
                        )}
                      </>
                    ),
                  }
                })}
              />
            </>
          )}
        </div>
      )}
    </Card>
  )
}
