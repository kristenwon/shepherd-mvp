'use client';

import { useEffect, useRef, useState } from 'react';
import cytoscape from 'cytoscape';

const AttackPathGraph = () => {
  const containerRef = useRef(null);
  const cyRef = useRef(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(2000); // milliseconds between steps

  const allSteps = [
    { id: 'step1', source: 'player', target: 'tool', label: '1. Initial Balance Check' },
    { id: 'step2', source: 'tool', target: 'pool', label: '2. Build FlashLoan Calls' },
    { id: 'step3', source: 'tool', target: 'pool', label: '3. Wrap in Multicall' },
    { id: 'step4', source: 'tool', target: 'forwarder', label: '4. Build MetaTx' },
    { id: 'step5', source: 'player', target: 'forwarder', label: '5. Sign MetaTx' },
    { id: 'step6', source: 'forwarder', target: 'pool', label: '6. Execute MetaTx' },
    { id: 'step6a', source: 'pool', target: 'receiver', label: '6a. Call FlashLoanReceiver' },
    { id: 'step6b', source: 'receiver', target: 'pool', label: '6b. Process Flash Loan' },
    { id: 'step7', source: 'tool', target: 'weth', label: '7. Check Balances' },
    { id: 'step8', source: 'tool', target: 'weth', label: '8. Calculate Total WETH' },
    { id: 'step9', source: 'tool', target: 'pool', label: '9. Build Withdraw' },
    { id: 'step10', source: 'tool', target: 'pool', label: '10. Wrap Withdraw' },
    { id: 'step11', source: 'tool', target: 'forwarder', label: '11. Build Withdraw MetaTx' },
    { id: 'step12', source: 'player', target: 'forwarder', label: '12. Sign Withdraw MetaTx' },
    { id: 'step13', source: 'forwarder', target: 'pool', label: '13. Execute Withdraw MetaTx' },
    { id: 'step14', source: 'player', target: 'weth', label: '14. Final Balance Check' }
  ];

  useEffect(() => {
    if (!containerRef.current) return;

    // Initialize Cytoscape
    const cy = cytoscape({
      container: containerRef.current,
      elements: {
        nodes: [
          // Player/Attacker node
          {
            data: {
              id: 'player',
              label: 'Attacker',
              type: 'player'
            },
            position: { x: 50, y: 300 }
          },
          // Tool Node
          {
            data: {
              id: 'tool',
              label: 'Tool Node',
              type: 'tool'
            },
            position: { x: 200, y: 200 }
          },
          // BasicForwarder
          {
            data: {
              id: 'forwarder',
              label: 'Forwarder',
              type: 'contract'
            },
            position: { x: 400, y: 100 }
          },
          // NaiveReceiverPool
          {
            data: {
              id: 'pool',
              label: 'ReceiverPool',
              type: 'contract'
            },
            position: { x: 600, y: 200 }
          },
          // FlashLoanReceiver
          {
            data: {
              id: 'receiver',
              label: 'LoanReceiver',
              type: 'contract'
            },
            position: { x: 600, y: 400 }
          },
          // WETH
          {
            data: {
              id: 'weth',
              label: 'WETH',
              type: 'token'
            },
            position: { x: 800, y: 300 }
          }
        ],
        edges: [] // Start with no edges
      },
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#666',
            'label': 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center',
            'width': 180,
            'height': 90,
            'font-size': '12px',
            'font-weight': 'bold',
            'color': 'white',
            'border-width': 2,
            'border-color': '#333'
          }
        },
        {
          selector: 'node[type = "player"]',
          style: {
            'background-color': '#FFD700',
            'shape': 'rectangle'
          }
        },
        {
          selector: 'node[type = "tool"]',
          style: {
            'background-color': '#4169E1',
            'shape': 'diamond'
          }
        },
        {
          selector: 'node[type = "contract"]',
          style: {
            'background-color': '#32CD32',
            'shape': 'ellipse'
          }
        },
        {
          selector: 'node[type = "token"]',
          style: {
            'background-color': '#FF6347',
            'shape': 'ellipse'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#ccc',
            'target-arrow-color': '#ccc',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '11px',
            'font-weight': 'bold',
            'color': 'white',
            'text-rotation': 'autorotate',
            'text-margin-y': '-20px',
            'text-wrap': 'wrap',
            'text-max-width': '120px',
            'text-background-color': 'rgba(0,0,0,0.9)',
            'text-background-padding': '4px',
            'text-border-color': '#666',
            'text-border-width': 1
          }
        },
        {
          selector: 'edge.highlighted',
          style: {
            'line-color': '#FFD700',
            'target-arrow-color': '#FFD700',
            'width': 4,
            'text-background-color': 'rgba(255,215,0,0.9)',
            'text-border-color': '#FFD700'
          }
        }
      ],
      layout: {
        name: 'preset',
        positions: {
          'player': { x: 50, y: 300 },
          'tool': { x: 200, y: 200 },
          'forwarder': { x: 400, y: 100 },
          'pool': { x: 600, y: 200 },
          'receiver': { x: 600, y: 400 },
          'weth': { x: 800, y: 300 }
        }
      }
    });

    cyRef.current = cy;

    // Fit the graph to the container
    cy.fit();

    // Cleanup function
    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
      }
    };
  }, []);

  // Function to add edges step by step
  const addStep = (stepIndex) => {
    if (!cyRef.current || stepIndex >= allSteps.length) return;
    
    const step = allSteps[stepIndex];
    const edge = cyRef.current.add({
      group: 'edges',
      data: {
        id: step.id,
        source: step.source,
        target: step.target,
        label: step.label
      }
    });

    // Highlight the current step
    cyRef.current.edges().removeClass('highlighted');
    edge.addClass('highlighted');

    // Fit the graph to show the new edge
    cyRef.current.fit();
  };

  // Function to reset the graph
  const resetGraph = () => {
    if (!cyRef.current) return;
    cyRef.current.elements('edge').remove();
    setCurrentStep(0);
  };

  // Function to show all steps
  const showAllSteps = () => {
    if (!cyRef.current) return;
    cyRef.current.elements('edge').remove();
    allSteps.forEach((step, index) => {
      setTimeout(() => {
        addStep(index);
        setCurrentStep(index + 1);
      }, index * 100);
    });
  };

  // Auto-play functionality
  useEffect(() => {
    if (!isPlaying) return;

    const interval = setInterval(() => {
      if (currentStep < allSteps.length) {
        addStep(currentStep);
        setCurrentStep(currentStep + 1);
      } else {
        setIsPlaying(false);
      }
    }, speed);

    return () => clearInterval(interval);
  }, [isPlaying, currentStep, speed]);

  return (
    <div className="w-full h-[500px] border border-gray-300 rounded-lg">
      <div className="p-4 bg-gray-50 border-b">
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold text-gray-800">
            Attack Path - NaiveReceiver Exploit (Step {currentStep}/{allSteps.length})
          </h3>
          <div className="flex space-x-2">
            <button
              onClick={() => {
                resetGraph();
                setIsPlaying(false);
              }}
              className="px-3 py-1 bg-gray-500 text-white rounded text-sm hover:bg-gray-600"
            >
              Reset
            </button>
            <button
              onClick={() => {
                if (isPlaying) {
                  setIsPlaying(false);
                } else {
                  if (currentStep >= allSteps.length) {
                    resetGraph();
                  }
                  setIsPlaying(true);
                }
              }}
              className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
            >
              {isPlaying ? 'Pause' : 'Play'}
            </button>
            <button
              onClick={() => {
                resetGraph();
                showAllSteps();
              }}
              className="px-3 py-1 bg-green-500 text-white rounded text-sm hover:bg-green-600"
            >
              Show All
            </button>
            <select
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="px-2 py-1 border rounded text-sm"
            >
              <option value={1000}>Fast</option>
              <option value={2000}>Normal</option>
              <option value={3000}>Slow</option>
            </select>
          </div>
        </div>
      </div>
      <div 
        ref={containerRef} 
        className="w-full h-96"
        style={{ minHeight: '400px' }}
      />
    </div>
  );
};

export default AttackPathGraph; 