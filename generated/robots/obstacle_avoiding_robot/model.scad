// Robot dimensions
chassis_w = 100;
chassis_l = 120;
chassis_h = 10;

wheel_r = 30;
wheel_w = 10;

sensor_size = 20;

// Chassis
color("gray") cube([chassis_w, chassis_l, chassis_h], center=true);

// Wheels
color("black") {
    translate([-chassis_w/2 - wheel_w/2, -chassis_l/4, 0]) rotate([0, 90, 0]) cylinder(r=wheel_r, h=wheel_w);
    translate([chassis_w/2 - wheel_w/2, -chassis_l/4, 0]) rotate([0, 90, 0]) cylinder(r=wheel_r, h=wheel_w);
}

// Controller (Arduino)
color("blue") translate([0, 0, chassis_h/2 + 5]) cube([50, 70, 10], center=true);

// Battery
color("green") translate([0, 30, chassis_h/2 + 5]) cube([40, 30, 15], center=true);

// Sensor
color("silver") translate([0, chassis_l/2 + sensor_size/2, chassis_h/2]) cube([sensor_size*2, sensor_size/2, sensor_size], center=true);
