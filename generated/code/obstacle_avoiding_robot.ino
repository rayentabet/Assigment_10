/*
 * Two-Wheel Obstacle-Avoiding Robot
 * 
 * Hardware:
 * - Arduino Uno/Nano
 * - L298N Motor Driver (or similar)
 * - 2x DC Motors with wheels
 * - 1x Caster wheel (back)
 * - HC-SR04 Ultrasonic Sensor
 * - 2x 9V batteries (one for Arduino, one for motors)
 * 
 * Wiring:
 * Motor A (Left Wheel):
 *   IN1 -> D5, IN2 -> D6
 * Motor B (Right Wheel):
 *   IN3 -> D7, IN4 -> D8
 * HC-SR04:
 *   Trig -> D9, Echo -> D10
 * 
 * Common GND between Arduino and motor driver must be connected!
 */

// ==================== PIN DEFINITIONS ====================

// Motor driver pins (PWM-capable for speed control)
const int LEFT_MOTOR_IN1 = 5;
const int LEFT_MOTOR_IN2 = 6;
const int RIGHT_MOTOR_IN3 = 7;
const int RIGHT_MOTOR_IN4 = 8;

// Ultrasonic sensor pins
const int TRIG_PIN = 9;
const int ECHO_PIN = 10;

// ==================== CONFIGURATION ====================

const int MOTOR_SPEED = 180;       // Motor speed (0-255)
const int TURN_SPEED = 150;        // Speed when turning (0-255)
const int OBSTACLE_DISTANCE = 20;  // Distance in cm to trigger avoidance
const int TURN_DURATION = 600;     // Turn duration in milliseconds

// ==================== SETUP ====================

void setup() {
  // Set motor pins as outputs
  pinMode(LEFT_MOTOR_IN1, OUTPUT);
  pinMode(LEFT_MOTOR_IN2, OUTPUT);
  pinMode(RIGHT_MOTOR_IN3, OUTPUT);
  pinMode(RIGHT_MOTOR_IN4, OUTPUT);

  // Set ultrasonic sensor pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Initialize serial for debugging
  Serial.begin(9600);
  Serial.println("Robot initialized!");
  Serial.println("Starting obstacle avoidance mode...");

  // Brief startup beep (optional - if buzzer is connected)
  delay(500);
}

// ==================== MAIN LOOP ====================

void loop() {
  // Read distance from ultrasonic sensor
  int distance = getDistance();

  // Debug output
  Serial.print("Distance: ");
  Serial.print(distance);
  Serial.println(" cm");

  // Check for obstacle
  if (distance < OBSTACLE_DISTANCE && distance > 0) {
    // Obstacle detected!
    Serial.println(">>> Obstacle detected! Avoiding...");
    avoidObstacle();
  } else {
    // No obstacle - move forward
    moveForward();
  }

  // Small delay for stability
  delay(50);
}

// ==================== MOTOR FUNCTIONS ====================

void moveForward() {
  // Left wheel forward
  analogWrite(LEFT_MOTOR_IN1, MOTOR_SPEED);
  digitalWrite(LEFT_MOTOR_IN2, LOW);

  // Right wheel forward
  analogWrite(RIGHT_MOTOR_IN3, MOTOR_SPEED);
  digitalWrite(RIGHT_MOTOR_IN4, LOW);
}

void stopMotors() {
  // Stop all motors
  digitalWrite(LEFT_MOTOR_IN1, LOW);
  digitalWrite(LEFT_MOTOR_IN2, LOW);
  digitalWrite(RIGHT_MOTOR_IN3, LOW);
  digitalWrite(RIGHT_MOTOR_IN4, LOW);
}

void turnRight() {
  // Left wheel forward, right wheel backward (pivot turn)
  analogWrite(LEFT_MOTOR_IN1, TURN_SPEED);
  digitalWrite(LEFT_MOTOR_IN2, LOW);

  digitalWrite(RIGHT_MOTOR_IN3, LOW);
  analogWrite(RIGHT_MOTOR_IN4, TURN_SPEED);
}

void turnLeft() {
  // Left wheel backward, right wheel forward (pivot turn)
  digitalWrite(LEFT_MOTOR_IN1, LOW);
  analogWrite(LEFT_MOTOR_IN2, TURN_SPEED);

  analogWrite(RIGHT_MOTOR_IN3, TURN_SPEED);
  digitalWrite(RIGHT_MOTOR_IN4, LOW);
}

void moveBackward() {
  // Left wheel backward
  digitalWrite(LEFT_MOTOR_IN1, LOW);
  analogWrite(LEFT_MOTOR_IN2, MOTOR_SPEED);

  // Right wheel backward
  digitalWrite(RIGHT_MOTOR_IN3, LOW);
  analogWrite(RIGHT_MOTOR_IN4, MOTOR_SPEED);
}

// ==================== OBSTACLE AVOIDANCE ====================

void avoidObstacle() {
  // Step 1: Stop
  stopMotors();
  delay(200);

  // Step 2: Back up a bit
  moveBackward();
  delay(400);
  stopMotors();
  delay(100);

  // Step 3: Look left and right to find the better direction
  int leftDistance = lookLeft();
  int rightDistance = lookRight();

  Serial.print("Left distance: ");
  Serial.print(leftDistance);
  Serial.print(" cm, Right distance: ");
  Serial.print(rightDistance);
  Serial.println(" cm");

  // Step 4: Turn toward the side with more space
  if (leftDistance > rightDistance) {
    Serial.println("Turning LEFT");
    turnLeft();
    delay(TURN_DURATION);
  } else {
    Serial.println("Turning RIGHT");
    turnRight();
    delay(TURN_DURATION);
  }

  // Step 5: Stop and resume forward
  stopMotors();
  delay(100);
}

// ==================== SENSOR FUNCTIONS ====================

int getDistance() {
  // Send a 10us pulse to Trig pin
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Read the echo pulse duration
  long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms timeout

  // Calculate distance in cm (speed of sound = 340 m/s)
  int distance = duration / 58.2;

  return distance;
}

int lookLeft() {
  // Turn left to scan
  turnLeft();
  delay(400);
  int dist = getDistance();
  stopMotors();
  delay(100);
  return dist;
}

int lookRight() {
  // Turn right to scan
  turnRight();
  delay(400);
  int dist = getDistance();
  stopMotors();
  delay(100);
  return dist;
}